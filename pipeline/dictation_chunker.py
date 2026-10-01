import re
import math
import logging

logger = logging.getLogger(__name__)


class DictationChunker:
    """Pre-node that intelligently splits long dictation text into coherent
    thematic and semantic chunks to avoid LLM context and output truncation."""

    MIN_SPLIT_THRESHOLD_WORDS = 1400
    TARGET_CHUNK_WORDS = 1100

    TRANSITION_CUES = [
        r"(?i)\b(?:siguiente\s+tema|pasamos\s+a(?:l)?|vamos\s+ahora\s+con|otro\s+tema|cambiando\s+de\s+tema|a\s+continuaci[oó]n|por\s+otro\s+lado|respecto\s+a(?:l)?|en\s+cuanto\s+a)\b",
    ]

    @classmethod
    def split(cls, text: str, target_chunk_words: int = None, min_threshold_words: int = None) -> list[str]:
        """Splits long text into thematic chunks. If text is short, returns [text]."""
        if not text or not text.strip():
            return []

        target_words = target_chunk_words or cls.TARGET_CHUNK_WORDS
        threshold = min_threshold_words or cls.MIN_SPLIT_THRESHOLD_WORDS

        words = text.split()
        total_words = len(words)

        if total_words <= threshold:
            return [text.strip()]

        num_chunks = max(2, round(total_words / target_words))
        words_per_chunk = total_words / num_chunks

        logger.info(
            f"DictationChunker: Dividing {total_words} words into {num_chunks} chunks (~{int(words_per_chunk)} words each)."
        )

        chunks = []
        current_char_pos = 0
        total_len = len(text)

        for i in range(1, num_chunks):
            # Target character position for cut point i
            target_word_idx = int(i * words_per_chunk)
            # Find char pos corresponding to target_word_idx
            approx_char_pos = cls._find_word_char_pos(text, target_word_idx)

            # Search window around approx_char_pos (±20% of words_per_chunk in chars)
            window_size = int(words_per_chunk * 5 * 0.35)  # ~5 chars per word * 35%
            window_start = max(current_char_pos + 100, approx_char_pos - window_size)
            window_end = min(total_len - 100, approx_char_pos + window_size)

            if window_start >= window_end:
                split_point = approx_char_pos
            else:
                split_point = cls._find_optimal_split_point(text, window_start, window_end, approx_char_pos)

            chunk = text[current_char_pos:split_point].strip()
            if chunk:
                chunks.append(chunk)
            current_char_pos = split_point

        # Remainder
        last_chunk = text[current_char_pos:].strip()
        if last_chunk:
            chunks.append(last_chunk)

        return chunks

    @staticmethod
    def _find_word_char_pos(text: str, word_idx: int) -> int:
        """Finds the approximate character index of the N-th word in text."""
        words_seen = 0
        for match in re.finditer(r'\S+', text):
            words_seen += 1
            if words_seen >= word_idx:
                return match.start()
        return len(text)

    @classmethod
    def _find_optimal_split_point(cls, text: str, start: int, end: int, ideal: int) -> int:
        """Selects the best cut point in [start, end] ordered by:
        1. Transition cues ('siguiente tema', 'pasamos a', etc.)
        2. Double newline (paragraph break)
        3. Single newline followed by heading or bullet
        4. Sentence ending (period + space + capital letter)
        5. Space
        """
        window = text[start:end]

        # 1. Search for paragraph breaks (\n\n), giving strong preference to those introducing transition cues
        best_para = None
        best_para_score = float("inf")
        for m in re.finditer(r'\n\s*\n', window):
            abs_pos = start + m.end()
            dist = abs(abs_pos - ideal)
            following = text[abs_pos : abs_pos + 80]
            has_cue = any(re.search(pat, following) for pat in cls.TRANSITION_CUES)
            score = dist - 800 if has_cue else dist
            if score < best_para_score:
                best_para_score = score
                best_para = abs_pos

        if best_para is not None:
            return best_para

        # 2. Search for transition cues (backtracking to preceding sentence start)
        best_cue = None
        best_cue_dist = float("inf")
        for pattern in cls.TRANSITION_CUES:
            for m in re.finditer(pattern, window):
                cue_start = start + m.start()
                pre_text = text[max(0, cue_start - 80) : cue_start]
                sent_match = re.search(r'(?:\.\s+|\n\s*|^)([^\.\n]*)$', pre_text)
                if sent_match and sent_match.group(1):
                    sentence_start_pos = cue_start - len(sent_match.group(1))
                else:
                    sentence_start_pos = cue_start

                dist = abs(sentence_start_pos - ideal)
                if dist < best_cue_dist:
                    best_cue_dist = dist
                    best_cue = sentence_start_pos

        if best_cue is not None:
            return best_cue

        # 3. Search for newline + bullet or dash
        best_bullet = None
        best_bullet_dist = float("inf")
        for m in re.finditer(r'\n(?=[-•*#])', window):
            abs_pos = start + m.start() + 1
            dist = abs(abs_pos - ideal)
            if dist < best_bullet_dist:
                best_bullet_dist = dist
                best_bullet = abs_pos

        if best_bullet is not None:
            return best_bullet

        # 4. Search for sentence ends (. followed by space and uppercase)
        best_sentence = None
        best_sentence_dist = float("inf")
        for m in re.finditer(r'\.\s+(?=[A-ZÁÉÍÓÚÑ])', window):
            abs_pos = start + m.start() + 1  # Cut right after period
            dist = abs(abs_pos - ideal)
            if dist < best_sentence_dist:
                best_sentence_dist = dist
                best_sentence = abs_pos

        if best_sentence is not None:
            return best_sentence

        # 5. Search for any period followed by whitespace
        for m in re.finditer(r'\.\s+', window):
            abs_pos = start + m.start() + 1
            dist = abs(abs_pos - ideal)
            if dist < best_sentence_dist:
                best_sentence_dist = dist
                best_sentence = abs_pos

        if best_sentence is not None:
            return best_sentence

        # 6. Fallback to space nearest to ideal
        best_space = ideal
        best_space_dist = float("inf")
        for m in re.finditer(r'\s+', window):
            abs_pos = start + m.start()
            dist = abs(abs_pos - ideal)
            if dist < best_space_dist:
                best_space_dist = dist
                best_space = abs_pos

        return best_space


class DictationAssembler:
    """Post-node that combines chunk-level generated notes into a cohesive,
    fully-structured Markdown document with consolidated metadata and questionnaire."""

    QUESTIONNAIRE_PATTERNS = [
        r"(?m)^#{2,3}\s+(?:Cuestionario\s+de\s+Autoevaluaci[oó]n|Autoevaluaci[oó]n(?:\s*\(Active\s+Recall\))?|Cuestionario\s+Active\s+Recall)\b",
    ]

    @classmethod
    def assemble(cls, chunk_notes: list[str]) -> str:
        """Assembles multiple Markdown chunks into a single document."""
        if not chunk_notes:
            return ""

        valid_chunks = [c.strip() for c in chunk_notes if c and c.strip()]
        if not valid_chunks:
            return ""

        if len(valid_chunks) == 1:
            return valid_chunks[0]

        yaml_header = ""
        combined_bodies = []
        all_questions = []

        for idx, note in enumerate(valid_chunks):
            note_content = note

            # Extract YAML from first chunk if present, strip it from subsequent chunks
            if note_content.startswith("---"):
                parts = note_content.split("---", 2)
                if len(parts) >= 3:
                    if idx == 0 and not yaml_header:
                        yaml_header = f"---{parts[1]}---\n\n"
                    note_content = parts[2].strip()

            # Separate questionnaire section if present
            found_q = False
            for pattern in cls.QUESTIONNAIRE_PATTERNS:
                match = re.search(pattern, note_content)
                if match:
                    body = note_content[:match.start()].strip()
                    q_part = note_content[match.end():].strip()
                    note_content = body
                    if q_part:
                        all_questions.append(q_part)
                    found_q = True
                    break

            if note_content:
                combined_bodies.append(note_content)

        # Build final markdown
        assembled_parts = []
        if yaml_header:
            assembled_parts.append(yaml_header.strip())

        if combined_bodies:
            assembled_parts.append("\n\n".join(combined_bodies))

        if all_questions:
            assembled_parts.append(
                "## Cuestionario de Autoevaluación\n\n" + "\n\n".join(all_questions)
            )

        final_doc = "\n\n".join(assembled_parts)
        # Ensure clean spacing around headers
        final_doc = re.sub(r'\n{3,}', '\n\n', final_doc)
        return final_doc.strip()
