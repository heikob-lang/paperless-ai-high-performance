#!/usr/bin/env python3
import sys
import os
import yaml
import time
import argparse
import logging
from pathlib import Path

try:
    from tqdm import tqdm
except ImportError:
    import subprocess
    subprocess.check_call([sys.executable, "-m", "pip", "install", "tqdm"])
    from tqdm import tqdm

# Logging Setup
logger = logging.getLogger("AI-Backfill")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logger.addHandler(handler)

# Basisverzeichnisse
CURRENT_DIR = Path(__file__).parent
sys.path.append(str(CURRENT_DIR))

# Import Custom Modules
from modules.paperless_client import PaperlessClient
from modules.llm_client import LLMClient
from modules.content_enhancer import ContentEnhancer
from modules.metadata_extractor import MetadataExtractor
from modules.duplicate_detector import DuplicateDetector
import import_to_openwebui

def load_config():
    config_path = CURRENT_DIR / "ai_config.yaml"
    if config_path.exists():
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    print("❌ Fehler: ai_config.yaml nicht gefunden.")
    sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description="Paperless-ngx AI Backfill")
    parser.add_argument("--force", action="store_true", help="Verarbeite Dokumente neu, auch wenn sie das 'paperless-ai' Tag haben")
    parser.add_argument("--check-duplicates", action="store_true", help="Aktiviere die KI-Duplikaterkennung auch für Altbestand (dauert länger!)")
    parser.add_argument("--id", type=int, help="Verarbeite nur eine spezifische Dokumenten-ID")
    parser.add_argument("--limit", type=int, default=0, help="Maximale Anzahl der zu verarbeitenden Dokumente (0 = alle)")
    args = parser.parse_args()

    print("🚀 Starte AI-Backfill für alte Dokumente...")
    config = load_config()

    paperless = PaperlessClient(config)
    llm = LLMClient(config)
    enhancer = ContentEnhancer(config, paperless, llm)
    extractor = MetadataExtractor(config, paperless, llm)
    detector = DuplicateDetector(config, paperless, llm)
    syncer = import_to_openwebui.OpenWebUISync()
    
    # Tag-ID für "ai-processed" ermitteln
    import requests
    tag_name = "ai-processed"
    ai_tag_id = None
    
    resp = requests.get(f"{paperless.api_url}/tags/?name__iexact={tag_name}", headers=paperless.headers)
    if resp.status_code == 200:
        res = resp.json().get('results', [])
        if res:
            ai_tag_id = res[0]['id']
            
    if not ai_tag_id:
        print(f"Erstelle neues Tag: {tag_name}")
        resp = requests.post(f"{paperless.api_url}/tags/", headers=paperless.headers, json={"name": tag_name, "color": "#00ff00"})
        if resp.status_code in (200, 201):
            ai_tag_id = resp.json()['id']
    
    print("\n🔍 Suche nach Dokumenten...")
    
    if args.id:
        docs_to_process = [{'id': args.id}]
        print(f"🎯 Verarbeite Einzel-ID: {args.id}")
    else:
        import urllib.parse
        query_params = {"page_size": 100, "ordering": "created"}
        if not args.force and ai_tag_id:
            query_params["tags__id__none"] = ai_tag_id
            
        qs = urllib.parse.urlencode(query_params)
        url = f"{paperless.api_url}/documents/?{qs}"
        
        docs_to_process = []
        try:
            while url:
                r = requests.get(url, headers=paperless.headers, timeout=30)
                r.raise_for_status()
                data = r.json()
                results = data.get('results', [])
                docs_to_process.extend(results)
                
                if args.limit > 0 and len(docs_to_process) >= args.limit:
                    docs_to_process = docs_to_process[:args.limit]
                    break
                url = data.get('next')
        except Exception as e:
            print(f"❌ Fehler beim Abfragen API: {e}")
            sys.exit(1)
            
        print(f"📊 {len(docs_to_process)} Dokumente gefunden.")

    if not docs_to_process:
        print("✅ Keine Dokumente zur Verarbeitung gefunden. Alles aktuell!")
        return

    import os
    import json
    progress_file = "/volume1/temp/ai_buffer/backfill_progress.json"
    processed_ids = set()
    if os.path.exists(progress_file):
        try:
            with open(progress_file, 'r', encoding='utf-8') as f:
                processed_ids = set(json.load(f))
            if processed_ids:
                print(f"🔄 Checkpoint geladen: {len(processed_ids)} Dokumente werden lokal übersprungen.")
        except:
            pass

    success_count = 0
    fail_count = 0
    
    for doc_item in tqdm(docs_to_process, desc="Verarbeite Dokumente", unit="Dok"):
        doc_id = doc_item['id']
        
        if doc_id in processed_ids:
            continue
        
        doc = paperless.get_document(doc_id)
        if not doc:
            fail_count += 1
            continue
            
        text_content = doc.get('content', '')
        if not text_content:
            fail_count += 1
            print(f"\n⚠️ Dokument {doc_id} hat keinen Text. Überspringe...")
            continue
            
        try:
            # 1. KI Zusammenfassung (Add Note)
            enhancer.process(document_id=doc_id, file_path=f"/fake/doc_{doc_id}.pdf", document_data={"content": text_content})
            
            # 2. KI Metadaten Extraktion
            extractor.process(document_id=doc_id, file_path=f"/fake/doc_{doc_id}.pdf", document_data={"content": text_content})
            
            # 2.5 Duplikaterkennung via ChromaDB
            if args.check_duplicates:
                already_duplicate = any('Duplikat' in note.get('note', '') for note in doc.get('notes', []))
                if already_duplicate:
                    print(f"\nℹ️ Überspringe KI-Duplikaterkennung: Dokument {doc_id} ist bereits als Duplikat markiert.")
                else:
                    detector.process(document_id=doc_id, file_path=f"/fake/doc_{doc_id}.pdf", document_data={"content": text_content})
            
            # 3. Open WebUI Sync
            metadata = paperless.get_document_metadata(doc_id)
            if metadata:
                media_root = Path(config['paperless'].get('media_root', '/usr/src/paperless/media'))
                arch_rel_path = metadata.get('archive_media_filename')
                orig_rel_path = metadata.get('media_filename')
                
                target_sync_file = None
                if arch_rel_path:
                    target = media_root / "documents" / "archive" / arch_rel_path
                    if target.exists(): target_sync_file = str(target)
                if not target_sync_file and orig_rel_path:
                    target = media_root / "documents" / "originals" / orig_rel_path
                    if target.exists(): target_sync_file = str(target)
                
                if target_sync_file:
                    try:
                        syncer.sync_single(target_sync_file)
                    except Exception as e:
                         print(f"\n⚠️ Fehler beim WebUI Upload (Dok {doc_id}): {e}")

            # 4. Final Tagging
            if ai_tag_id:
                current_tags = doc.get('tags', [])
                if ai_tag_id not in current_tags:
                    current_tags.append(ai_tag_id)
                    paperless.update_document(doc_id, {"tags": current_tags})
                    
            success_count += 1
            processed_ids.add(doc_id)
            try:
                os.makedirs(os.path.dirname(progress_file), exist_ok=True)
                with open(progress_file, 'w', encoding='utf-8') as f:
                    json.dump(list(processed_ids), f)
            except Exception as e:
                pass
            
        except Exception as e:
            print(f"\n❌ Absturz bei Dokument {doc_id}: {e}")
            fail_count += 1

    # Cleanup
    print("\n🧹 LLM Speicher wird geleert...")
    llm.unload_model(llm.model)
    if hasattr(llm, 'summary_model') and llm.summary_model != llm.model:
        llm.unload_model(llm.summary_model)

    print("\n" + "="*40)
    print(f"🎉 BACKFILL ABGESCHLOSSEN")
    print(f"✅ Erfolgreich: {success_count} / {len(docs_to_process)}")
    print("="*40)

if __name__ == "__main__":
    main()
