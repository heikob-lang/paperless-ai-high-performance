#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ChromaDB Cleanup Script für Paperless AI
Bereinigt verwaiste Einträge und alte Sidecar-Dateien.

Wird als Cronjob im ai-worker Container ausgeführt.
"""
import os
import sys
import time
import glob
import yaml
import requests

# Pfad-Setup
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from modules.chroma_client import ChromaClient

# Konfiguration
CONFIG_PATH = os.path.join(current_dir, 'ai_config.yaml')
SIDECAR_DIR = "/volume1/temp/ai_buffer"
SIDECAR_MAX_AGE_HOURS = 24


def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)


def cleanup_chromadb(config):
    """Entfernt ChromaDB-Einträge für gelöschte Paperless-Dokumente."""
    print("🔍 Starte ChromaDB Cleanup...")
    
    try:
        chroma = ChromaClient()
    except Exception as e:
        print(f"ChromaDB nicht erreichbar: {e}")
        return
    
    all_chroma_ids = chroma.get_all_doc_ids()
    print(f"ChromaDB enthält {len(all_chroma_ids)} Dokumente")
    
    if not all_chroma_ids:
        return
    
    # Paperless API Setup
    api_url = config['paperless']['url']
    token = config['paperless']['token']
    headers = {
        "Authorization": f"Token {token}",
        "Content-Type": "application/json"
    }
    
    deleted_count = 0
    
    for doc_id in all_chroma_ids:
        try:
            resp = requests.get(
                f"{api_url}/documents/{doc_id}/",
                headers=headers,
                timeout=10
            )
            if resp.status_code == 404:
                # Dokument existiert nicht mehr in Paperless
                chroma.delete_document(doc_id)
                deleted_count += 1
                print(f"🗑️ Verwaistes Dokument {doc_id} aus ChromaDB entfernt")
            elif resp.status_code != 200:
                print(f"⚠️ Unerwarteter Status für Dokument {doc_id}: {resp.status_code}")
        except Exception as e:
            print(f"Fehler bei Prüfung von Dokument {doc_id}: {e}")
    
    print(f"✅ ChromaDB Cleanup abgeschlossen: {deleted_count} verwaiste Einträge entfernt")


def cleanup_sidecars():
    """Löscht Sidecar-JSON-Dateien die älter als SIDECAR_MAX_AGE_HOURS sind."""
    print(f"🧹 Räume Sidecar-Dateien auf (älter als {SIDECAR_MAX_AGE_HOURS}h)...")
    
    if not os.path.exists(SIDECAR_DIR):
        print(f"Sidecar-Verzeichnis {SIDECAR_DIR} existiert nicht")
        return
    
    now = time.time()
    max_age_seconds = SIDECAR_MAX_AGE_HOURS * 3600
    deleted_count = 0
    
    for json_file in glob.glob(os.path.join(SIDECAR_DIR, "*.json")):
        try:
            file_age = now - os.path.getmtime(json_file)
            if file_age > max_age_seconds:
                os.remove(json_file)
                deleted_count += 1
                print(f"🗑️ Alte Sidecar-Datei gelöscht: {os.path.basename(json_file)}")
        except Exception as e:
            print(f"Fehler beim Löschen von {json_file}: {e}")
    
    print(f"✅ Sidecar Cleanup abgeschlossen: {deleted_count} Dateien gelöscht")


def main():
    print("=" * 50)
    print("🔧 Paperless AI Cleanup Service")
    print(f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    
    config = load_config()
    
    # 1. ChromaDB bereinigen
    cleanup_chromadb(config)
    
    # 2. Sidecar-Dateien aufräumen
    cleanup_sidecars()
    
    print("\n✅ Alle Cleanup-Aufgaben abgeschlossen.")


if __name__ == "__main__":
    # Kann als einmaliger Lauf oder als Loop betrieben werden
    if "--loop" in sys.argv:
        interval_hours = 6
        print(f"🔄 Loop-Modus: Alle {interval_hours}h")
        while True:
            try:
                main()
            except Exception as e:
                print(f"Cleanup Loop Fehler: {e}")
            time.sleep(interval_hours * 3600)
    else:
        main()
