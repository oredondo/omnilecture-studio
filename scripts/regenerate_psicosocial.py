import os
import sys
import re
import time
import logging

# Add project root directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import config
import pipeline_config
from pipeline.generate_notes import NotesGenerator
from pipeline.graph import EIRNotesGraph
from pipeline.pdf_compiler.compiler import compile_markdowns_to_pdf

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(os.path.join(config.OUTPUT_DIR, "pipeline_execution.log"))
    ]
)
logger = logging.getLogger("RegeneratePsicosocial")

def run():
    base_name = "psicosocial segunda"
    notes_dir = os.path.join(config.OUTPUT_DIR, "apuntes")
    bruto_dir = os.path.join(notes_dir, "bruto")
    os.makedirs(bruto_dir, exist_ok=True)
    
    raw_ocr_path = os.path.join(bruto_dir, f"{base_name}_ocr_bruto.txt")
    raw_trans_path = os.path.join(bruto_dir, f"{base_name}_transcripcion_bruto.txt")
    existing_notes_path = os.path.join(notes_dir, f"{base_name}_apuntes_EIR.md")
    
    if not os.path.exists(raw_trans_path):
        raise FileNotFoundError(f"Transcripción bruta no encontrada: {raw_trans_path}")
    if not os.path.exists(raw_ocr_path):
        raise FileNotFoundError(f"OCR bruto no encontrado: {raw_ocr_path}")
        
    logger.info("Cargando transcripción y OCR brutos...")
    with open(raw_trans_path, "r", encoding="utf-8") as f:
        trans_content = f.read()
    with open(raw_ocr_path, "r", encoding="utf-8") as f:
        ocr_content = f.read()
        
    generator = NotesGenerator(
        video_path=os.path.join(config.OUTPUT_DIR, f"{base_name}.mp4"),
        audio_path=os.path.join(config.OUTPUT_DIR, f"{base_name}.mp3"),
        generate_anki=False,
        ocr_file=raw_ocr_path,
        trans_file=raw_trans_path
    )
    
    chunk_minutes = getattr(pipeline_config, "OCR_CHUNK_MINUTES", 30)
    logger.info(f"Dividiendo textos en bloques de {chunk_minutes} minutos...")
    ocr_chunks = generator._split_text_by_time(ocr_content, chunk_minutes)
    trans_chunks = generator._split_text_by_time(trans_content, chunk_minutes)
    
    logger.info(f"Chunks disponibles: {len(trans_chunks)} de audio, {len(ocr_chunks)} de OCR.")
    
    # 1. Recuperar Chunks 1-4 existentes (minutos 0 a 120) si existen en el fichero actual
    # Cortado justo antes de la línea incompleta de Jacobson
    chunk_1_4_path = os.path.join(bruto_dir, f"{base_name}_chunks_01_04.md")
    if not os.path.exists(chunk_1_4_path) and os.path.exists(existing_notes_path):
        with open(existing_notes_path, "r", encoding="utf-8") as ef:
            current_text = ef.read()
        # Cortar en la cabecera incompleta de Técnicas de Relajación Específicas
        cut_idx = current_text.find("## Técnicas de Relajación Específicas")
        if cut_idx != -1:
            part1_4 = current_text[:cut_idx].strip()
        else:
            part1_4 = current_text.strip()
            
        with open(chunk_1_4_path, "w", encoding="utf-8") as pf:
            pf.write(part1_4)
        logger.info(f"Guardado checkpoint de chunks 1-4 ({len(part1_4.split())} palabras) en {chunk_1_4_path}")
    else:
        logger.info(f"Checkpoint de chunks 1-4 ya existente en {chunk_1_4_path}")

    # 2. Procesar Chunks 5, 6, 7, 8 (minutos 120 a 216)
    graph = EIRNotesGraph()
    clean_title = "psicosocial segunda"
    subject = "Enfermería Clínica"
    
    chunk_files = []
    
    # Añadir chunks 1-4
    with open(chunk_1_4_path, "r", encoding="utf-8") as pf:
        chunk_files.append(pf.read())
        
    for chunk_idx in range(4, len(trans_chunks)):
        chunk_num = chunk_idx + 1
        chunk_file_path = os.path.join(bruto_dir, f"{base_name}_chunk_{chunk_num:02d}.md")
        
        if os.path.exists(chunk_file_path) and os.path.getsize(chunk_file_path) > 200:
            logger.info(f"Reutilizando chunk {chunk_num} ya procesado desde {chunk_file_path}")
            with open(chunk_file_path, "r", encoding="utf-8") as cf:
                chunk_files.append(cf.read())
            continue
            
        tc = trans_chunks[chunk_idx] if chunk_idx < len(trans_chunks) else ""
        oc = ocr_chunks[chunk_idx] if chunk_idx < len(ocr_chunks) else ""
        
        logger.info(f"--- Procesando Chunk {chunk_num}/{len(trans_chunks)} ({len(tc.split())} palabras de transcripción) ---")
        chunk_title = f"{clean_title} - Parte {chunk_num}"
        
        chunk_notes, _ = graph.run(
            ocr_content=oc,
            transcription_content=tc,
            title=chunk_title,
            subject=subject,
            generate_anki=False
        )
        
        with open(chunk_file_path, "w", encoding="utf-8") as cf:
            cf.write(chunk_notes)
        logger.info(f"Chunk {chunk_num} completado y guardado en {chunk_file_path} ({len(chunk_notes.split())} palabras)")
        chunk_files.append(chunk_notes)
        
    # 3. Combinar todos los bloques
    logger.info("Unificando todos los bloques de la clase...")
    combined_bodies = []
    combined_questions = []
    first_yaml = ""
    
    for idx, notes_md in enumerate(chunk_files):
        parts = notes_md.split("---")
        if len(parts) >= 3:
            if idx == 0:
                first_yaml = "---" + parts[1] + "---\n\n"
            body_and_q = "---".join(parts[2:]).strip()
        else:
            body_and_q = notes_md.strip()
            
        q_split = body_and_q.split("## Cuestionario de Autoevaluación")
        body = q_split[0].strip()
        questionnaire = q_split[1].strip() if len(q_split) > 1 else ""
        
        if body:
            combined_bodies.append(body)
        if questionnaire:
            combined_questions.append(questionnaire)
            
    final_merged = first_yaml + "\n\n".join(combined_bodies)
    if combined_questions:
        final_merged += "\n\n## Cuestionario de Autoevaluación\n" + "\n\n".join(combined_questions)
        
    logger.info(f"Documento consolidado total: {len(final_merged.split())} palabras, {len(final_merged.splitlines())} líneas.")
    
    # 4. Refinamiento editorial en chunks (ZERO INFORMATION LOSS)
    logger.info("Iniciando refinamiento editorial seguro en chunks...")
    final_refined = generator._refine_notes_in_chunks(graph.llm, final_merged)
    
    # 5. Guardar documento final definitivo
    output_notes_path = os.path.join(notes_dir, f"{base_name}_apuntes_EIR.md")
    with open(output_notes_path, "w", encoding="utf-8") as out_f:
        out_f.write(final_refined)
    logger.info(f"[ÉXITO] Documento completo guardado en: {output_notes_path}")
    
    # 6. Compilar a PDF optimizado
    logger.info("Compilando PDF optimizado con google-chrome...")
    pdf_path, layout = compile_markdowns_to_pdf(
        md_sources=output_notes_path,
        font_size_mode="normal",
        organize=False
    )
    logger.info(f"[ÉXITO] PDF compilado satisfactoriamente en: {pdf_path}")
    print(f"\n=======================================================")
    print(f"PROCESAMIENTO COMPLETO FINALIZADO CON ÉXITO")
    print(f"Apuntes Markdown: {output_notes_path}")
    print(f"PDF Optimizado:   {pdf_path}")
    print(f"=======================================================\n")

if __name__ == "__main__":
    run()
