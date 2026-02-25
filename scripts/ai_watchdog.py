#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
PAPERLESS AI WATCHDOG SERVICE
Überwacht /usr/src/paperless/scan_input, optimiert PDFs und verschiebt sie nach /consume.
"""

import os
import sys
import shutil
import base64
import logging
import subprocess
import time
import io
from pathlib import Path
from typing import Any, TYPE_CHECKING
import json
import threading
import queue

# Queue für entkoppelte KI-Verarbeitung (Producer-Consumer)
ocr_queue = queue.Queue()

# Force UTF-8 for stdout/stderr
if sys.stdout.encoding != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
if sys.stderr.encoding != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# ─── KONFIGURATION ───
WATCH_DIR = Path("/usr/src/paperless/scan_input")
CONSUME_DIR = Path("/usr/src/paperless/consume")
MD_BUFFER_DIR = Path("/volume1/temp/ai_buffer")
STAGING_DIR = Path("/volume1/temp/ai_staging")
GPU_BUSY_FLAG = Path("/volume1/temp/.gpu_busy")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
# Model-Namen werden jetzt aus der Config gelesen

DPI = 300            # Ausgewogene Auflösung (400 war zu langsam bei extrem großen PDFs)
RESIZE_MAX = 3072    # Mehr Details für die KI (Qwen verträgt das)

logging.basicConfig(level=logging.INFO, format='%(asctime)s [AI-WATCHDOG] %(message)s')
logger = logging.getLogger()

import requests
from PIL import Image, ImageEnhance, ImageFilter
from pdf2image import convert_from_path

# Old optimize function removed. Used DocumentOptimizer instead.

# get_ai_text wurde entfernt. Wird nun über LLMClient abgewickelt.

import hashlib
import yaml

# ... imports ...

def calculate_md5(file_path: Path) -> str:
    """Berechnet den MD5-Hash einer Datei (kompatibel mit Paperless Checksummen)."""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def load_config():
    config_path = Path(__file__).parent / "ai_config.yaml"
    if config_path.exists():
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    return {}

def process_file_single(input_file: Path):
    logger.info(f"🚀 Starte Verarbeitung für: {input_file.name}")
    
    # Eindeutige UID (MD5 der Binärdatei) für sauberes Tracking durch das ganze System berechnen
    # WICHTIG: Paperless nutzt MD5 für Checksummen-Anfragen.
    try:
        uid = calculate_md5(input_file)
    except Exception as e:
        logger.error(f"Konnte MD5 nicht berechnen: {e}")
        return False
        
    # 0. Check for Binary Duplicates (Paperless-Database)
    try:
        sys.path.append(str(Path(__file__).parent))
        from modules.paperless_client import PaperlessClient
        from modules.llm_client import LLMClient
        
        config = load_config()
        if config:
            client = PaperlessClient(config)
            llm_client = LLMClient(config)
            duplicate = client.get_document_by_checksum(uid)
            
            if duplicate:
                dup_id = duplicate.get('id')
                dup_title = duplicate.get('title')
                
                # Zombie Check: Ask API for exact metadata paths
                file_exists = False
                metadata = client.get_document_metadata(dup_id)
                
                if metadata:
                    media_root = Path(config['paperless'].get('media_root', '/usr/src/paperless/media'))
                    orig_rel_path = metadata.get('media_filename')
                    arch_rel_path = metadata.get('archive_media_filename')
                    
                    if orig_rel_path and (media_root / "documents" / "originals" / orig_rel_path).exists():
                        file_exists = True
                    elif arch_rel_path and (media_root / "documents" / "archive" / arch_rel_path).exists():
                        file_exists = True
                else:
                    # Fallback if metadata fails for some reason but DB entry exists
                    file_exists = True


                if file_exists:
                    logger.warning(f"⚠️ BINÄRES DUPLIKAT von Dok #{dup_id} ('{dup_title}') erkannt.")
                    
                    # Move to duplicates folder
                    dup_dir = WATCH_DIR / "duplicates"
                    dup_dir.mkdir(exist_ok=True)
                    target = dup_dir / input_file.name
                    
                    # Wenn Ziel schon existiert, Timestamp anhängen
                    if target.exists():
                       target = dup_dir / f"{input_file.stem}_{int(time.time())}{input_file.suffix}"
                    
                    shutil.move(str(input_file), str(target))
                    logger.info(f"✅ Verschiebe in Duplikat-Ordner: {target.name}")
                    return True
                else:
                    logger.warning(f"⚠️ Zombie-Duplikat in DB (ID {dup_id}), aber Datei physisch nicht gefunden. Verarbeite als NEU.")
    except Exception as e:
        logger.error(f"Error checking binary duplicates: {e}")

        # 0b. Quick pre‑vision duplicate check using extracted PDF text (if any)
        # Bei Vektor‑Ähnlichkeit: Dokument wird NICHT blockiert, sondern importiert.
        # Eine Notiz mit Vergleichs‑Link wird angehängt → User entscheidet selbst.
        duplicate_info = {}
        try:
            from pdfminer.high_level import extract_text
            raw_text = extract_text(str(input_file))
            if raw_text and raw_text.strip():
                try:
                    embedding = llm_client.generate_embedding(raw_text)
                except Exception as embed_err:
                    logger.error(f"Embedding‑Fehler im Vor‑Duplicate‑Check: {embed_err}")
                    embedding = None
                if embedding:
                    try:
                        from modules.chroma_client import ChromaClient
                        chroma = ChromaClient()
                        similar = chroma.find_similar(raw_text, threshold=0.95, n_results=1)
                        if similar:
                            orig_id = similar[0].get("id")
                            sim_score = similar[0].get("similarity", 0.95)
                            logger.info(f"⚠️ Vektor‑Ähnlichkeit ({sim_score:.0%}) mit Dok #{orig_id} erkannt für {input_file.name}. Importiere trotzdem – User entscheidet.")
                            duplicate_info = {
                                "is_duplicate": True,
                                "original_id": orig_id,
                                "similarity": round(sim_score, 4)
                            }
                    except Exception as chroma_err:
                        logger.error(f"Chroma‑Abfrage‑Fehler im Vor‑Duplicate‑Check: {chroma_err}")
        except Exception as e:
            logger.error(f"Fehler beim schnellen Vor‑Duplicate‑Check: {e}")

        # 1. Setup Workdir
        MD_BUFFER_DIR.mkdir(parents=True, exist_ok=True)
        work_dir = Path("/volume1/temp") / f"watch_work_{int(time.time())}_{input_file.name}"
        img_dir = work_dir / "imgs"
        img_dir.mkdir(parents=True, exist_ok=True)
    
    # Import DocumentOptimizer
    sys.path.append(str(Path(__file__).parent))
    try:
        from modules.document_optimizer import DocumentOptimizer
        optimizer = DocumentOptimizer(dpi=DPI, resize_max=RESIZE_MAX)
    except ImportError:
        logger.error("Could not import DocumentOptimizer")
        return False

    try:
        # 2. PDF -> Bilder (nur für Analyse, maximal 10 Seiten!)
        image_paths = convert_from_path(str(input_file), dpi=DPI, output_folder=str(img_dir), fmt='jpeg', paths_only=True, thread_count=8, last_page=10)
        image_paths.sort()
        
        page_texts = []
        optimized_images_b64 = [] 
        
        # Optimiere alle Bilder nur in Base64 Strings, speichere sie im RAM
        for p in image_paths:
            p_path = Path(p)
            b64 = optimizer.optimize_image(p_path)
            optimized_images_b64.append(b64)

        # 2.5. Verschiebe das Original umgehend in den temp Staging-Ordner, um Endlosschleifen der CPU zu verhindern!
        STAGING_DIR.mkdir(parents=True, exist_ok=True)
        staged_file = STAGING_DIR / f"{uid}.pdf"
        shutil.move(str(input_file), str(staged_file))
        os.chmod(staged_file, 0o666)

        # 3. AI Analysis Loop in die Queue auslagern
        logger.info(f"✅ CPU-Extraktion beendet. Füge {len(image_paths)} Seiten zur KI-Warteschlange hinzu.")
        
        # Lege das Arbeitspaket für den GPU-Thread bereit
        queue_item = {
            "uid": uid,
            "original_filename": input_file.name,
            "staged_file": staged_file,
            "work_dir": work_dir,
            "b64_images": optimized_images_b64,
            "duplicate_info": duplicate_info
        }
        ocr_queue.put(queue_item)
        
        # Watchdog-Schleife ist hier fertig und kann sofort das nächste PDF entpacken!
        return True

    except Exception as e:
        logger.error(f"Fehler bei CPU-Analyse von {input_file.name}: {e}")
        
        # Fail-Safe: Aber NICHT blind nach consume verschieben!
        # Erst prüfen, ob es ein Duplikat ist – sonst erzeugen wir ConsumerErrors.
        try:
            if input_file.exists():
                # Duplikat-Check vor dem Verschieben
                file_md5 = calculate_md5(input_file)
                is_known_dup = False
                
                try:
                    config = load_config()
                    if config:
                        from modules.paperless_client import PaperlessClient
                        client = PaperlessClient(config)
                        dup = client.get_document_by_checksum(file_md5)
                        if dup:
                            is_known_dup = True
                            logger.info(f"⚠️ (Fail-Safe) Bekanntes Duplikat von '{dup.get('title')}' (#{dup.get('id')}). Verschiebe in duplicates-Ordner.")
                except Exception:
                    pass  # API nicht erreichbar → sicherheitshalber nach consume lassen
                
                if is_known_dup:
                    dup_dir = Path("/usr/src/paperless/scan_input/duplicates")
                    dup_dir.mkdir(exist_ok=True)
                    target = dup_dir / input_file.name
                    if target.exists():
                        target = dup_dir / f"{input_file.stem}_{int(time.time())}{input_file.suffix}"
                    shutil.move(str(input_file), str(target))
                    logger.info(f"✅ (Fail-Safe) Duplikat nach duplicates verschoben: {target.name}")
                else:
                    # Kein bekanntes Duplikat → nach consume (Paperless versucht es)
                    logger.warning("⚠️ Überspringe KI-Analyse und übergebe direkt an Paperless (Fail-Safe).")
                    target_consume = CONSUME_DIR / input_file.name
                    shutil.move(str(input_file), str(target_consume))
                    os.chmod(target_consume, 0o666)
                    logger.info(f"✅ (Fail-Safe) Original nach consume verschoben: {input_file.name}")
            return True
        except Exception as move_e:
            logger.error(f"Kritischer Fehler beim Verschieben (Fail-Safe): {move_e}")
            return False

def gpu_worker():
    """Hintergrund-Thread: Holt Bilder aus der Warteschlange und sendet sie nacheinander an Ollama (GPU)"""
    logger.info("🤖 GPU-Worker Thread gestartet. Warte auf Bilder...")
    
    config = load_config()
    sys.path.append(str(Path(__file__).parent))
    try:
        from modules.llm_client import LLMClient
        llm_client = LLMClient(config)
    except ImportError:
        logger.error("GPU-Worker konnte LLMClient nicht laden!")
        return
        
    prompt = config.get('prompts', {}).get('ocr_base', "Erkenne den Text in diesem Bild exakt.")
    
    while True:
        try:
            item = ocr_queue.get()
            uid = item["uid"]
            original_filename = item["original_filename"]
            staged_file = item["staged_file"]
            work_dir = item["work_dir"]
            b64_images = item["b64_images"]
            
            # GPU als besetzt markieren (für das dynamische Routing im Host)
            GPU_BUSY_FLAG.touch()
            
            remaining = ocr_queue.qsize()  # Gibt die Anzahl der wartenden Elemente zurück
            logger.info(f"🤖 GPU beginnt mit OCR für: {original_filename} (UID: {uid[:8]}...) | Noch {remaining} Dokument(e) in der Warteschlange.")
            page_texts = []
            
            for i, b64 in enumerate(b64_images):
                text = ""
                if llm_client:
                    text = llm_client.generate(prompt=prompt, images=[b64])
                    
                if not text: text = "[OCR FEHLER]"
                page_texts.append(text)
                logger.info(f"🤖 Seite {i+1}/{len(b64_images)} von {original_filename} analysiert.")
                
            # Fallunterscheidung: NEU vs. RETROACTIVE
            retro_doc_id = item.get("retro_doc_id")
            
            if retro_doc_id:
                # ─── RETROACTIVE PFAD ───
                # Dokument existiert bereits in Paperless, wir updaten es direkt via API
                logger.info(f"🔄 Updating Paperless Doc #{retro_doc_id} directly...")
                try:
                    from modules.paperless_client import PaperlessClient
                    client = PaperlessClient(config)
                    
                    # 1. Text-Inhalt updaten
                    client.session.patch(f"{client.api_url}/documents/{retro_doc_id}/", json={
                        "content": full_ai_text
                    })
                    
                    # 2. Tags verwalten: processing -> done
                    client.remove_tag(retro_doc_id, "AI-OCR-processing")
                    client.add_tag(retro_doc_id, "AI-OCR-done")
                    
                    # 3. Staging File löschen (wird nicht mehr für consume benötigt)
                    if staged_file.exists():
                        staged_file.unlink()
                        
                    logger.info(f"✅ Retroactive OCR abgeschlossen für Doc #{retro_doc_id}.")
                except Exception as api_err:
                    logger.error(f"❌ API-Update Fehler bei Retro‑OCR Doc #{retro_doc_id}: {api_err}")
            else:
                # ─── STANDARD PFAD (NEUE SCANS) ───
                # JSON Sidecar schreiben (Benenne es mit der UID für fehlerfreie Zuordnung!)
                MD_BUFFER_DIR.mkdir(parents=True, exist_ok=True)
                sidecar_json = MD_BUFFER_DIR / (f"{uid}.json")
                sidecar_data = {
                    "metadata": {},
                    "duplicate_info": item.get("duplicate_info", {}),
                    "ai_content": full_ai_text,
                    "scan_date": time.time(),
                    "original_filename": original_filename,
                    "uid": uid
                }
                sidecar_json.write_text(json.dumps(sidecar_data, indent=2, default=str), encoding="utf-8")
                os.chmod(sidecar_json, 0o666)
                
                # Original-PDF aus dem Staging in den paperless Consume Ordner verschieben
                target_consume = CONSUME_DIR / original_filename
                shutil.move(str(staged_file), str(target_consume))
                os.chmod(target_consume, 0o666)
                logger.info(f"✅ GPU-Job beendet. Dokument bereit für Paperless: {original_filename}")
            
            # Workdir Cleanup
            if work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
                
            # Job erledigt
            ocr_queue.task_done()
            
            # Wenn Warteschlange leer, GPU als frei markieren (für Text-Jobs im Host)
            if ocr_queue.empty():
                if GPU_BUSY_FLAG.exists():
                    GPU_BUSY_FLAG.unlink()
                    logger.info("🟢 GPU ist nun wieder frei für Text-Aufgaben.")
            
        except Exception as e:
            # Im Fehlerfall Flagge sicherheitshalber auch entfernen
            if GPU_BUSY_FLAG.exists():
                GPU_BUSY_FLAG.unlink()
            logger.error(f"Fehler im GPU-Worker: {e}")
            if 'work_dir' in locals() and work_dir.exists():
                shutil.rmtree(work_dir, ignore_errors=True)
            if 'staged_file' in locals():
                try:
                    # Im schlimmsten Fall versuchen, das Dokument un-KIdentifiziert zu Paperless zu schieben
                    target_consume = CONSUME_DIR / original_filename
                    if staged_file.exists():
                        shutil.move(str(staged_file), str(target_consume))
                        os.chmod(target_consume, 0o666)
                        logger.warning(f"⚠️ GPU-Crash. Dokument rübergeschoben: {original_filename}")
                except:
                    pass
            try:
                ocr_queue.task_done()
            except:
                pass


def recover_staged_files():
    """Wird beim Start aufgerufen, um abgebrochene Jobs aus dem Staging-Ordner wiederherzustellen und alte Temp-Ordner zu löschen."""
    
    # 1. Temp-Ordner bereinigen (Staging Leftovers)
    logger.info("🧹 Bereinige alte Temp-Arbeitsordner...")
    temp_dir = Path("/volume1/temp")
    if temp_dir.exists():
        for old_work in temp_dir.glob("watch_work_*"):
            if old_work.is_dir():
                try:
                    shutil.rmtree(old_work, ignore_errors=True)
                except Exception as e:
                    logger.warning(f"Konnte Temp-Ordner {old_work.name} nicht löschen: {e}")
                    
    # 2. Gestrandete PDFs aus Staging holen
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    staged_pdfs = list(STAGING_DIR.glob("*.pdf"))
    
    if not staged_pdfs:
        return
        
    logger.info(f"🔄 Stelle {len(staged_pdfs)} abgebrochene Dokumente aus dem Staging-Ordner wieder her...")
    
    try:
        sys.path.append(str(Path(__file__).parent))
        from modules.document_optimizer import DocumentOptimizer
        from modules.paperless_client import PaperlessClient
        
        optimizer = DocumentOptimizer(dpi=DPI, resize_max=RESIZE_MAX)
        config = load_config()
        client = PaperlessClient(config) if config else None
        
    except:
        logger.error("Konnte Module für Recovery nicht laden!")
        return
        
    for staged_file in staged_pdfs:
        try:
            uid = staged_file.stem
            
            # 1. Prüfen ob dieses Dokument vielleicht schon VOR dem letzten Crash erfolgreich in Paperless ankam!
            # Berechne die MD5 der physischen Datei (uid = Dateiname, sollte der MD5 entsprechen)
            actual_md5 = calculate_md5(staged_file)
            
            if client:
                # Doppelte Absicherung: Prüfe sowohl mit Dateiname-UID als auch mit der echten berechneten MD5
                for checksum_candidate in set([uid, actual_md5]):
                    duplicate = client.get_document_by_checksum(checksum_candidate)
                    if duplicate:
                        logger.info(f"👻 Ghost File erkannt: {staged_file.name} existiert bereits als '{duplicate.get('title')}' (ID {duplicate.get('id')}) in Paperless! Lösche Dateileiche...")
                        staged_file.unlink()
                        break
                else:
                    # Kein Duplikat gefunden → weiter mit Recovery
                    pass
                
                if not staged_file.exists():
                    continue
            
            logger.info(f"🔄 Recovering: {staged_file.name}")
            
            # Wir haben den Original-Namen verloren (er ist jetzt die UID).
            # Fallback auf generischen Namen für Paperless
            original_filename = f"recovered_{uid[:8]}.pdf"
            
            # Bilder neu rendern (wir haben die alten in /volume1/temp/watch_work... durch Restart evtl. verloren)
            work_dir = Path("/volume1/temp") / f"recovery_{uid[:8]}"
            img_dir = work_dir / "imgs"
            img_dir.mkdir(parents=True, exist_ok=True)
            
            image_paths = convert_from_path(str(staged_file), dpi=DPI, output_folder=str(img_dir), fmt='jpeg', paths_only=True, thread_count=8, last_page=10)
            image_paths.sort()
            
            optimized_images_b64 = []
            for p in image_paths:
                b64 = optimizer.optimize_image(Path(p))
                optimized_images_b64.append(b64)
                
            queue_item = {
                "uid": uid,
                "original_filename": original_filename,
                "staged_file": staged_file,
                "work_dir": work_dir,
                "b64_images": optimized_images_b64
            }
            ocr_queue.put(queue_item)
            logger.info(f"✅ Recovery erfolgreich: {staged_file.name} wieder in die Warteschlange eingefügt.")
            
        except Exception as e:
            logger.error(f"❌ Fehler bei Recovery von {staged_file.name}: {e}")
            try:
                # Fallback nach Consume
                target = CONSUME_DIR / staged_file.name
                shutil.move(str(staged_file), str(target))
                os.chmod(target, 0o666)
            except:
                pass


def ai_retagger():
    """Prüft regelmäßig auf Dokumente mit dem Tag 'AI-OCR' und reiht sie in die Pipeline ein."""
    logger.info("🕵️ Retroactive OCR Poller gestartet. Suche alle 5 Minuten nach 'AI-OCR' Tags...")
    
    while True:
        try:
            config = load_config()
            if not config:
                time.sleep(60)
                continue
                
            from modules.paperless_client import PaperlessClient
            from modules.document_optimizer import DocumentOptimizer
            client = PaperlessClient(config)
            optimizer = DocumentOptimizer(dpi=DPI, resize_max=RESIZE_MAX)
            
            # Suche nach Dokumenten mit Tag 'AI-OCR'
            # Format: ?tags__name__iexact=AI-OCR
            url = f"{client.api_url}/documents/?tags__name__iexact=AI-OCR"
            response = client.session.get(url)
            
            if response.status_code == 200:
                docs = response.json().get('results', [])
                for doc in docs:
                    doc_id = doc.get('id')
                    title = doc.get('title')
                    
                    # 1. Metadaten holen für MD5 Checksumme (UID)
                    meta = client.get_document_metadata(doc_id)
                    uid = meta.get('archive_checksum') or meta.get('original_checksum')
                    
                    if not uid:
                        logger.warning(f"⚠️ Konnte keine Checksumme für Dokument #{doc_id} finden. Überspringe...")
                        continue
                        
                    logger.info(f"🎯 Retroactive OCR Triggered: Dokument #{doc_id} ('{title}')")
                    
                    # 2. Download nach Staging
                    temp_pdf = STAGING_DIR / f"{uid}.pdf"
                    if client.download_document(doc_id, temp_pdf):
                        # 3. Vorbereiten für Pipeline
                        work_dir = Path("/volume1/temp") / f"retro_{uid[:8]}"
                        img_dir = work_dir / "imgs"
                        img_dir.mkdir(parents=True, exist_ok=True)
                        
                        image_paths = convert_from_path(str(temp_pdf), dpi=DPI, output_folder=str(img_dir), fmt='jpeg', paths_only=True, thread_count=8, last_page=10)
                        image_paths.sort()
                        
                        optimized_images_b64 = []
                        for p in image_paths:
                            b64 = optimizer.optimize_image(Path(p))
                            optimized_images_b64.append(b64)
                            
                        # 4. In GPU Queue werfen
                        queue_item = {
                            "uid": uid,
                            "original_filename": f"{title}.pdf",
                            "staged_file": temp_pdf,
                            "work_dir": work_dir,
                            "b64_images": optimized_images_b64,
                            "retro_doc_id": doc_id # WICHTIG: Damit wir wissen, was wir updaten müssen
                        }
                        ocr_queue.put(queue_item)
                        
                        # 5. Tag wechseln: AI-OCR -> AI-OCR-processing (damit wir nicht in Schleifen laufen)
                        client.remove_tag(doc_id, "AI-OCR")
                        client.add_tag(doc_id, "AI-OCR-processing")
                        
                        logger.info(f"✅ Dokument #{doc_id} ('{title}') erfolgreich in die Queue eingereiht.")
                    else:
                        logger.error(f"❌ Download fehlgeschlagen für Dokument #{doc_id}")
            
            # Alle 5 Minuten prüfen
            time.sleep(300)
            
        except Exception as e:
            logger.error(f"Fehler im ai_retagger: {e}")
            time.sleep(60)


def main():
    logger.info(f"AI Watchdog gestartet. Überwache: {WATCH_DIR}")
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    (WATCH_DIR / "error").mkdir(exist_ok=True)
    
    # Starte den GPU Consumer Thread
    gpu_thread = threading.Thread(target=gpu_worker, daemon=True)
    gpu_thread.start()
    
    # Starte den Retroactive OCR Poller
    retagger_thread = threading.Thread(target=ai_retagger, daemon=True)
    retagger_thread.start()
    
    # Resource Saver Setup
    sys.path.append(str(Path(__file__).parent))
    from modules.container_manager import ContainerManager
    container_mgr = ContainerManager()
    cpu_container_name = load_config().get('ollama', {}).get('cpu_container_name', 'paperless_ollama_cpu')
    last_activity_time = time.time()
    IDLE_TIMEOUT = 300 # 5 Minuten
    
    # Abgebrochene Jobs vom letzten Absturz/Restart wiederherstellen
    recover_staged_files()
    
    while True:
        try:
            # Suche nach PDFs
            files = sorted([f for f in WATCH_DIR.glob("*.pdf") if f.is_file()], key=os.path.getmtime)
            
            # Neue Dateien nacheinander verarbeiten
            if files:
                last_activity_time = time.time()
                for pdf in files:
                    try:
                        if not pdf.exists(): continue
                        
                        # Prüfe ob Datei gerade geschrieben wird
                        initial_size = pdf.stat().st_size
                        time.sleep(1)
                        if pdf.exists() and pdf.stat().st_size != initial_size:
                            continue
                        
                        # Direkt verarbeiten
                        process_file_and_cleanup(pdf)
                        
                    except Exception as inner_e:
                        logger.error(f"Fehler bei der Verarbeitung von {pdf.name}: {inner_e}")
            
            # Resource Saver Logic: Stop CPU container after 5 min idle
            if ocr_queue.empty():
                idle_duration = time.time() - last_activity_time
                if idle_duration > IDLE_TIMEOUT:
                    if container_mgr.is_running(cpu_container_name):
                        logger.info(f"💤 CPU-Container Idle ({int(idle_duration)}s). Fahre herunter...")
                        container_mgr.stop_container(cpu_container_name)
            else:
                # Warteschlange ist nicht leer -> Aktivität!
                last_activity_time = time.time()
                
            time.sleep(5)
            
        except KeyboardInterrupt:
            logger.info("Watchdog beendet.")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Globaler Loop Fehler: {e}")
            time.sleep(5)

def process_file_and_cleanup(full_path: Path):
    try:
        success = process_file_single(full_path)
        if not success:
            # Bei Fehlern in den Error-Ordner
            error_dir = WATCH_DIR / "error"
            shutil.move(str(full_path), str(error_dir / full_path.name))
    except Exception as e:
        logger.error(f"Kritischer Fehler bei Verarbeitung von {full_path.name}: {e}")
        try:
             shutil.move(str(full_path), str(WATCH_DIR / "error" / full_path.name))
        except: pass

if __name__ == "__main__":
    main()
