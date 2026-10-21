#import <Foundation/Foundation.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreMedia/CoreMedia.h>
#import <AVFoundation/AVFoundation.h>
#include <signal.h>
#include <math.h>

static volatile sig_atomic_t keep_running = 1;
static void handle_sig(int sig) {
    keep_running = 0;
}

static double current_host_pts(void) {
    return CMTimeGetSeconds(CMClockGetTime(CMClockGetHostTimeClock()));
}

@interface AudioCaptureDelegate : NSObject <SCStreamOutput, SCStreamDelegate>
@property (nonatomic, assign) FILE *wavFile;
@property (nonatomic, assign) uint32_t sampleRate;
@property (nonatomic, assign) uint32_t dataBytes;
@property (nonatomic, assign) uint64_t totalSamplesWritten;
@property (nonatomic, assign) double firstPts;
@property (nonatomic, copy) NSString *ptsPath;
- (void)padSilenceToPts:(double)targetPts;
@end

@implementation AudioCaptureDelegate

- (void)saveFirstPts:(double)pts {
    self.firstPts = pts;
    if (self.ptsPath) {
        NSString *ptsStr = [NSString stringWithFormat:@"%.6f\n", self.firstPts];
        [ptsStr writeToFile:self.ptsPath atomically:YES encoding:NSUTF8StringEncoding error:nil];
    }
}

- (void)padSilenceToPts:(double)targetPts {
    if (!self.wavFile || self.firstPts <= 0.0 || self.sampleRate == 0) {
        return;
    }
    double expectedPts = self.firstPts + ((double)self.totalSamplesWritten / (double)self.sampleRate);
    double gapSec = targetPts - expectedPts;
    if (gapSec > 0.005 && gapSec < 7200.0) {
        int padSamples = (int)llround(gapSec * (double)self.sampleRate);
        if (padSamples > 0) {
            int16_t *zeros = calloc(padSamples, sizeof(int16_t));
            if (zeros) {
                fwrite(zeros, sizeof(int16_t), padSamples, self.wavFile);
                self.dataBytes += (uint32_t)(padSamples * sizeof(int16_t));
                self.totalSamplesWritten += (uint64_t)padSamples;
                free(zeros);
            }
        }
    }
}

- (void)stream:(SCStream *)stream didOutputSampleBuffer:(CMSampleBufferRef)sampleBuffer ofType:(SCStreamOutputType)type {
    if (type != SCStreamOutputTypeAudio || !CMSampleBufferDataIsReady(sampleBuffer)) {
        return;
    }

    CMTime ptsTime = CMSampleBufferGetPresentationTimeStamp(sampleBuffer);
    double pts = CMTIME_IS_VALID(ptsTime) ? CMTimeGetSeconds(ptsTime) : 0.0;

    AudioBufferList abl;
    CMBlockBufferRef blockBuffer = NULL;
    OSStatus status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
        sampleBuffer,
        NULL,
        &abl,
        sizeof(abl),
        NULL,
        NULL,
        kCMSampleBufferFlag_AudioBufferList_Assure16ByteAlignment,
        &blockBuffer
    );
    if (status != noErr || abl.mNumberBuffers == 0) {
        if (blockBuffer) CFRelease(blockBuffer);
        return;
    }

    float *samples = (float *)abl.mBuffers[0].mData;
    int numSamples = abl.mBuffers[0].mDataByteSize / sizeof(float);
    if (samples && numSamples > 0 && self.wavFile) {
        @synchronized (self) {
            if (pts > 0.0) {
                if (self.firstPts <= 0.0 || (self.totalSamplesWritten == 0 && pts < self.firstPts)) {
                    [self saveFirstPts:pts];
                } else {
                    [self padSilenceToPts:pts];
                }
            }

            int16_t *pcm = malloc(numSamples * sizeof(int16_t));
            if (pcm) {
                for (int i = 0; i < numSamples; i++) {
                    float s = samples[i];
                    if (s > 1.0f) s = 1.0f;
                    if (s < -1.0f) s = -1.0f;
                    pcm[i] = (int16_t)(s * 32767.0f);
                }
                fwrite(pcm, sizeof(int16_t), numSamples, self.wavFile);
                self.dataBytes += (uint32_t)(numSamples * sizeof(int16_t));
                self.totalSamplesWritten += (uint64_t)numSamples;
                free(pcm);
            }
        }
    }
    if (blockBuffer) {
        CFRelease(blockBuffer);
    }
}
@end

static void write_wav_header(FILE *f, uint32_t sampleRate, uint16_t channels, uint32_t dataBytes) {
    fseek(f, 0, SEEK_SET);
    uint32_t fileSize = 36 + dataBytes;
    uint32_t fmtSize = 16;
    uint16_t audioFormat = 1;
    uint32_t byteRate = sampleRate * channels * 2;
    uint16_t blockAlign = channels * 2;
    uint16_t bitsPerSample = 16;
    fwrite("RIFF", 1, 4, f);
    fwrite(&fileSize, 4, 1, f);
    fwrite("WAVEfmt ", 1, 8, f);
    fwrite(&fmtSize, 4, 1, f);
    fwrite(&audioFormat, 2, 1, f);
    fwrite(&channels, 2, 1, f);
    fwrite(&sampleRate, 4, 1, f);
    fwrite(&byteRate, 4, 1, f);
    fwrite(&blockAlign, 2, 1, f);
    fwrite(&bitsPerSample, 2, 1, f);
    fwrite("data", 1, 4, f);
    fwrite(&dataBytes, 4, 1, f);
}

int main(int argc, char *argv[]) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <output.wav> [sample_rate]\n", argv[0]);
        return 1;
    }
    signal(SIGINT, handle_sig);
    signal(SIGTERM, handle_sig);

    @autoreleasepool {
        NSString *outPath = [NSString stringWithUTF8String:argv[1]];
        uint32_t sr = 48000;
        if (argc >= 3) {
            int parsedSr = atoi(argv[2]);
            if (parsedSr == 8000 || parsedSr == 16000 || parsedSr == 24000 || parsedSr == 48000) {
                sr = (uint32_t)parsedSr;
            }
        }

        FILE *f = fopen([outPath UTF8String], "wb");
        if (!f) {
            return 1;
        }
        write_wav_header(f, sr, 1, 0);

        dispatch_semaphore_t sem = dispatch_semaphore_create(0);
        __block SCStream *stream = nil;
        __block BOOL startedOk = NO;
        AudioCaptureDelegate *delegate = [[AudioCaptureDelegate alloc] init];
        delegate.wavFile = f;
        delegate.sampleRate = sr;
        delegate.dataBytes = 0;
        delegate.totalSamplesWritten = 0;
        delegate.firstPts = 0.0;
        delegate.ptsPath = [outPath stringByAppendingString:@".pts"];

        [SCShareableContent getShareableContentWithCompletionHandler:^(SCShareableContent *content, NSError *error) {
            if (error || content.displays.count == 0) {
                dispatch_semaphore_signal(sem);
                return;
            }
            SCDisplay *display = content.displays.firstObject;
            SCContentFilter *filter = [[SCContentFilter alloc] initWithDisplay:display excludingWindows:@[]];
            SCStreamConfiguration *cfg = [[SCStreamConfiguration alloc] init];
            cfg.capturesAudio = YES;
            cfg.excludesCurrentProcessAudio = NO;
            cfg.sampleRate = sr;
            cfg.channelCount = 1;
            cfg.width = 64;
            cfg.height = 64;
            cfg.minimumFrameInterval = CMTimeMake(1, 2);

            stream = [[SCStream alloc] initWithFilter:filter configuration:cfg delegate:delegate];
            NSError *addErr = nil;
            [stream addStreamOutput:delegate
                               type:SCStreamOutputTypeAudio
                 sampleHandlerQueue:dispatch_get_global_queue(QOS_CLASS_USER_INTERACTIVE, 0)
                              error:&addErr];
            [stream startCaptureWithCompletionHandler:^(NSError *startErr) {
                startedOk = (startErr == nil);
                if (startedOk) {
                    @synchronized (delegate) {
                        if (delegate.firstPts <= 0.0) {
                            [delegate saveFirstPts:current_host_pts()];
                        }
                    }
                }
                dispatch_semaphore_signal(sem);
            }];
        }];
        dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 5 * NSEC_PER_SEC));

        if (!startedOk) {
            fclose(f);
            return 2;
        }

        while (keep_running) {
            usleep(20000);
        }

        double stopPts = current_host_pts();
        if (stream) {
            dispatch_semaphore_t stopSem = dispatch_semaphore_create(0);
            [stream stopCaptureWithCompletionHandler:^(NSError *stopErr) {
                dispatch_semaphore_signal(stopSem);
            }];
            dispatch_semaphore_wait(stopSem, dispatch_time(DISPATCH_TIME_NOW, 2 * NSEC_PER_SEC));
        }

        @synchronized (delegate) {
            [delegate padSilenceToPts:stopPts];
        }

        write_wav_header(f, sr, 1, delegate.dataBytes);
        fflush(f);
        fclose(f);
    }
    return 0;
}
