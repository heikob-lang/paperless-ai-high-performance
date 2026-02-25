#!/usr/bin/env python3
import os
import sys
import json
import yaml
import argparse
import requests
from pathlib import Path




# Ensure modules structure is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from modules.paperless_client import PaperlessClient
from modules.llm_client import LLMClient
from modules.duplicate_detector import DuplicateDetector
from modules.metadata_extractor import MetadataExtractor
from modules.content_enhancer import ContentEnhancer

# Load Configuration
CONFIG_PATH = os.path.join(current_dir, 'ai_config.yaml')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}")
        sys.exit(0)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def perform_vision_retry(doc_id, file_path, original_filename, doc_data, config, paperless, llm):
    """Führt eine Vision-basierte Extraktion als Fallback durch, falls kein Sidecar existiert."""
    try:
        import shutil
        import time
        from pdf2image import convert_from_path
        from modules.document_optimizer import DocumentOptimizer
        
        vision_input_path = None
        is_native_image = False
        
        if file_path and os.path.exists(file_path):
            ext = os.path.splitext(file_path)[1].lower()
            if ext in ['.pdf']:
                vision_input_path = file_path
            elif ext in ['.jpg', '.jpeg', '.png', '.tiff', '.bmp']:
                vision_input_path = file_path
                is_native_image = True
            else:
                print(f"Original is {ext}. checking for Archive PDF...")
                archived_name = doc_data.get('archived_file_name')
                if archived_name:
                    media_root = config['paperless'].get('media_root', '/usr/src/paperless/media')
                    archive_full_path = os.path.join(media_root, "archive", archived_name)
                    if os.path.exists(archive_full_path):
                        print(f"Found Archive PDF: {archive_full_path}")
                        vision_input_path = archive_full_path
                    else:
                        print(f"Archive file not found at {archive_full_path}")
        
        if not vision_input_path:
            return {}

        print(f"Using {vision_input_path} for Vision Analysis...")
        
        retry_work_dir = Path("/volume1/temp") / f"post_retry_{doc_id}_{int(time.time())}"
        retry_work_dir.mkdir(parents=True, exist_ok=True)
        img_dir = retry_work_dir / "imgs"
        img_dir.mkdir(parents=True, exist_ok=True)
        
        optimizer = DocumentOptimizer()
        b64_images = []
        
        if is_native_image:
            b64 = optimizer.optimize_image(Path(vision_input_path))
            if b64:
                b64_images.append(b64)
        else:
            image_paths = convert_from_path(vision_input_path, dpi=300, output_folder=str(img_dir), fmt='jpeg', paths_only=True)
            image_paths.sort()
            for p in image_paths:
                b64 = optimizer.optimize_image(Path(p))
                if b64:
                    b64_images.append(b64)
        
        sidecar_data = {}
        if b64_images:
            extractor = MetadataExtractor(config, paperless, llm)
            print("🤖 Running Vision OCR (Retry)...")
            ai_content = extractor.extract_text_from_images(b64_images)
            
            print("🤖 Running Vision Metadata Extraction (Retry)...")
            metadata = extractor.extract_metadata_from_image(b64_images[0])
            
            # VRAM von Vision Model nach Retry NICHT mehr hier befreien, da Watchdog es parallel nutzen könnte!
            # llm.unload_model(llm.vision_model)
            
            sidecar_data = {
                "metadata": metadata,
                "duplicate_info": {}, 
                "ai_content": ai_content,
                "scan_date": time.time(),
                "original_filename": original_filename,
                "is_retry": True
            }
            print("✅ Vision Retry Successful! Generated in-memory sidecar data.")
        
        if retry_work_dir.exists():
            shutil.rmtree(retry_work_dir, ignore_errors=True)
            
        return sidecar_data
        
    except Exception as e:
        print(f"❌ Vision Retry Failed: {e}. Falling back to standard processing.")
        return {}


def main():
    # 1. Parse Arguments from Paperless
    # Paperless passes: document_id, file_path, source_path, original_filename, etc.
    # But usually just defined by env vars or positional args depending on configuration.
    # The standard post-consume script receives:
    # $1 = Document ID
    # $2 = File Name (original)
    # $3 = Source Path
    # $4 = Thumbnail Path
    # $5 = Download URL
    # $6 = Thumbnail URL
    # $7 = Correspondent
    # $8 = Tags
    
    # However, Paperless documentation says:
    # DOCUMENT_ID, DOCUMENT_FILE_NAME, DOCUMENT_SOURCE_PATH, ... are passed as ENV VARS
    # AND script is called with arguments: document_id, file_path, ...
    
    parser = argparse.ArgumentParser(description='Paperless AI Post-Consume Script')
    parser.add_argument('document_id', help='Paperless Document ID')
    parser.add_argument('file_path', help='Path to the processed file', nargs='?')
    
    args, unknown = parser.parse_known_args()
    
    doc_id = args.document_id
    file_path = args.file_path

    # Extract original filename from file_path or env var if available
    # Paperless passes the original filename as argument 2 often, but we parse args.
    # Check env var DOCUMENT_ORIGINAL_FILENAME
    original_filename = os.environ.get("DOCUMENT_ORIGINAL_FILENAME")
    if not original_filename and file_path:
         original_filename = os.path.basename(file_path)

    print(f"--- AI Pipeline Started for Document {doc_id} ({original_filename}) ---")

    # Determine original source path to calculate UID
    env_source = os.environ.get("DOCUMENT_SOURCE_PATH")
    original_pdf_path = Path(env_source) if env_source else (Path(file_path) if file_path else None)
    
    uid = None
    if original_pdf_path and original_pdf_path.exists():
        import hashlib
        hash_sha256 = hashlib.sha256()
        with open(original_pdf_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_sha256.update(chunk)
        uid = hash_sha256.hexdigest()
        print(f"File UID (SHA256): {uid}")

    # 2. Init
    config = load_config()
    
    paperless = PaperlessClient(config)
    llm = LLMClient(config)
    
    # 2.5 Fetch Document Metadata (Moved up for Retry Logic)
    doc_data = paperless.get_document(doc_id)
    if not doc_data:
        print(f"Error: Could not fetch metadata for document {doc_id}")
        sys.exit(0)
    
    # 3. Check for Sidecar JSON (from AI Watchdog)
    # This is the "Memory" of our pre-processing, strictly mapped via SHA256 UID
    if uid:
        sidecar_path = os.path.join("/volume1/temp/ai_buffer", f"{uid}.json")
    else:
        sidecar_path = os.path.join("/volume1/temp/ai_buffer", f"{original_filename}.json")
        
    sidecar_data = {}
    
    if os.path.exists(sidecar_path):
        print(f"Found Sidecar JSON: {sidecar_path}")
        try:
            with open(sidecar_path, 'r', encoding='utf-8') as f:
                sidecar_data = json.load(f)
            
            # Aufräumen: Datei löschen, da sie nun gelesen wurde
            try:
                os.remove(sidecar_path)
                print(f"✅ Sidecar JSON gelöscht: {sidecar_path}")
            except Exception as delete_error:
                print(f"Konnte Sidecar JSON nicht löschen: {delete_error}")
                
        except Exception as e:
            print(f"Error loading Sidecar JSON: {e}")
            sidecar_data = {}
    else:
         print(f"No Sidecar JSON found at {sidecar_path}. Attempting Vision Rewrite (Retry Mode)...")
         sidecar_data = perform_vision_retry(doc_id, file_path, original_filename, doc_data, config, paperless, llm)

    # 4. Fetch Document Metadata (from Paperless)
    doc_data = paperless.get_document(doc_id)
    if not doc_data:
        print(f"Error: Could not fetch metadata for document {doc_id} on second try")
        sys.exit(0)

    # 4.5 AI Content Override
    # Wenn der Watchdog layoutgetreuen AI-Text geliefert hat,
    # überschreiben wir das Paperless content-Feld damit VOR der Modul-Pipeline.
    # Das verhindert den typischen Zeilenmix bei mehrspaltigen Dokumenten und 
    # gibt dem Duplikat-Checker die echte Textbasis.
    ai_content = sidecar_data.get("ai_content", "")
    if ai_content and len(ai_content) > 50:
        try:
            paperless.update_document(doc_id, {"content": ai_content})
            doc_data["content"] = ai_content # Wichtig: In-Memory Update für die Module!
            print(f"✅ Content updated with AI-OCR text ({len(ai_content)} Zeichen)")
        except Exception as e:
            print(f"Error updating content: {e}")
    else:
        print("Kein AI-Content im Sidecar vorhanden, Paperless-OCR wird beibehalten.")


    # 5. Pipeline Execution
    modules = []
    
    # 5.1 Duplicate Detection
    # If sidecar says it's a duplicate, we trust it!
    dup_info = sidecar_data.get("duplicate_info", {})
    if dup_info.get("is_duplicate"):
        print(f"✅ Sidecar indicates DUPLICATE of {dup_info.get('original_id')}")
        # Add Note/Tag immediately
        original_id = dup_info.get('original_id')
        link = paperless.get_document_link(original_id)
        compare_link = paperless.get_comparison_link(original_id, doc_id)
        
        note_text = (
            f"⚠️ Erkanntes Duplikat von Dokument {original_id}\n\n"
            f"Zum Vergleichen kopieren Sie diesen Link:\n"
            f"{compare_link}\n\n"
            f"(Prüfung durch AI Watchdog)"
        )
        paperless.add_note(doc_id, note_text)
        # TODO: Add Tag "Duplicate" if you have the ID
    elif config['modules']['duplicate_detector'].get('enabled', False):
        # Fallback: Run standard detector if no sidecar info or not a duplicate
        modules.append(DuplicateDetector(config, paperless, llm))

    # 5.2 Metadata Extractor
    # If sidecar has metadata, use it?
    # For now, let's allow re-extraction or merge. 
    # Metadata extraction in post-consume might filter/refine what Watchdog did.
    # But Watchdog used Qwen2.5-VL which is strong.
    md_from_sidecar = sidecar_data.get("metadata", {})
    if md_from_sidecar:
         print("Using Metadata from Sidecar...")
         # Directly update using sidecar data?
         # Or let the module handle it? 
         # Let's pass it to the module if we modify the module signature, 
         # OR just update here.
         # For simplicity, let's just update here if we trust it.
         # But the MetadataExtractor module has logic to map fields.
         # Let's stick to the module for consistency, but maybe we can inject the data?
         pass # For now, run the module as normally. It's fast enough.

    if config['modules']['metadata_extractor'].get('enabled', False):
        modules.append(MetadataExtractor(config, paperless, llm))

    # 5.3 Content Enhancer
    if config['modules']['content_enhancer'].get('enabled', False):
        modules.append(ContentEnhancer(config, paperless, llm))
    
    # Run Modules
    for module in modules:
        try:
            module.process(doc_id, file_path, doc_data)
        except Exception as e:
            print(f"Error in module {module.__class__.__name__}: {e}")

    # 7. ChromaDB Indexierung
    try:
        from modules.chroma_client import ChromaClient
        chroma = ChromaClient()
        index_content = ai_content if (ai_content and len(ai_content) > 50) else doc_data.get('content', '')
        fresh_doc = paperless.get_document(doc_id)
        meta = {
            "title": fresh_doc.get('title', '') if fresh_doc else '',
            "correspondent": str(fresh_doc.get('correspondent', '')) if fresh_doc else '',
        }
        chroma.add_document(int(doc_id), index_content, meta)
    except Exception as e:
        print(f"ChromaDB Indexierung fehlgeschlagen (nicht kritisch): {e}")

    # 8. ARCHIVE GENERATION (The "Archive Only" Workflow)
    # Deaktiviert: Rasterisierung und Graustufen-Konvertierung zerstören 'normale Layouts inkl. Grafik'.
    # Wir belassen das exzellente Standard-Archivdokument von Paperless.
    print("--- Using Standard Paperless Archive ---")
    
    # Paperless stellt Umgebungsvariablen für die Pfade des Originals und des generierten Archivs zur Verfügung
    original_pdf_path = None
    archive_path_str = None
    
    env_source = os.environ.get("DOCUMENT_SOURCE_PATH")
    env_archive = os.environ.get("DOCUMENT_ARCHIVE_PATH")
    
    if env_source:
         original_pdf_path = Path(env_source)
    elif file_path:
         original_pdf_path = Path(file_path)
         
    if env_archive:
         archive_path_str = env_archive

    # 10. Open WebUI Sync
    try:
        print("--- Syncing to Open WebUI ---")
        # Ensure we can import the script
        import import_to_openwebui
        syncer = import_to_openwebui.OpenWebUISync()
        
        # Decide which file to sync: Archive (preferred) or Original
        target_sync_file = None
        
        # Nutzen der explizit initialisierten Variablen
        if archive_path_str and os.path.exists(archive_path_str):
             target_sync_file = archive_path_str
        elif original_pdf_path and original_pdf_path.exists():
             target_sync_file = str(original_pdf_path)
        else:
             target_sync_file = file_path # Default fallback
             
        if target_sync_file and os.path.exists(target_sync_file):
            syncer.sync_single(target_sync_file)
        else:
            print(f"⚠️  No file to sync found.")
            
    except Exception as e:
        print(f"❌ Open WebUI Sync Error: {e}")

    print("--- AI Pipeline Finished ---")

    # 9. Final Tagging: "AI-Processed"
    # Indicates that the document has successfully passed the pipeline
    try:
        tag_name = "ai-processed"
        # Check if tag exists (implied logic: try adding, if ID unknown need fetch)
        # Simple approach: Search tag, create if missing, add to doc.
        
        # 1. Search Tag
        tag_id = None
        resp = requests.get(f"{paperless.api_url}/tags/?name__iexact={tag_name}", headers=paperless.headers)
        if resp.status_code == 200:
            results = resp.json().get('results', [])
            if results:
                tag_id = results[0]['id']
        
        # 2. Create if missing
        if not tag_id:
            print(f"Creating tag '{tag_name}'...")
            resp = requests.post(
                f"{paperless.api_url}/tags/",
                headers=paperless.headers,
                json={"name": tag_name, "color": "#00ff00", "is_inbox_tag": False}
            )
            if resp.status_code in (200, 201):
                tag_id = resp.json().get('id')
        
        # 3. Add to Document
        if tag_id:
            # Re-fetch doc to get current tags (to avoid overwriting concurrent edits?)
            # We just updated content/archive, so we should have fresh state or fetch it.
            # safe update: append to list.
            current_doc = paperless.get_document(doc_id)
            if current_doc:
                current_tags = current_doc.get('tags', [])
                if tag_id not in current_tags:
                    current_tags.append(tag_id)
                    paperless.update_document(doc_id, {"tags": current_tags})
                    print(f"✅ Tag '{tag_name}' added.")
    except Exception as e:
        print(f"Error adding final tag: {e}")

    # LLM Cleanup VRAM - DEAKTIVIERT!
    # Da der asynchrone Watchdog (GPU Worker) jetzt Modelle permanent im Hintergrund braucht,
    # darf dieser synchrone Prozess sie ihm nicht unterm Hintern wegziehen.
    # print("🧹 Cleaning up remaining LLM models from VRAM...")
    # llm.unload_model(llm.model)
    # if hasattr(llm, 'summary_model') and llm.summary_model != llm.model:
    #     llm.unload_model(llm.summary_model)
    # llm.unload_model(llm.embedding_model)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"CRITICAL ERROR in ai_post_consume.py: {e}")
        # Always exit 0 to prevent Paperless from throwing a ConsumerError and failing the document
        sys.exit(0)
