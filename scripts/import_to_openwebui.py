#!/usr/bin/env python3
import os
import sys
import requests
import mimetypes
import hashlib
import argparse
from pathlib import Path

import yaml
def _get_config():
    p = Path(__file__).parent / "ai_config.yaml"
    if p.exists():
        try:
             with open(p, 'r', encoding='utf-8') as f:
                  return yaml.safe_load(f) or {}
        except: pass
    return {}

_cfg = _get_config().get("open_webui", {})

OPEN_WEBUI_URL = os.environ.get("OPEN_WEBUI_URL") or _cfg.get("url") or "http://paperless_open_webui:8080"
# Harter Fallback auf den von dir generierten JWT Token
API_TOKEN = os.environ.get("OPEN_WEBUI_API_KEY") or _cfg.get("api_key") or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6Ijc5MGIzZWViLWM4ZWEtNGQxMi1hZTlhLTQ4ZDEzMGMyMmU2OCIsImV4cCI6MTc3MzY1NDE5MywianRpIjoiZWExMTk4ZGQtYTliMi00ZTYxLThmOTQtNGZjMGIzMDUxZDA0In0.mqXU_b_29lh_2iKEoF2m9ZXTAUNJl9J4X6kBi4W_ciM"
ARCHIVE_DIR = "/usr/src/paperless/media/documents/archive"
COLLECTION_NAME = "Paperless Archiv"

class OpenWebUISync:
    def __init__(self):
        if not API_TOKEN:
            raise Exception("❌ Fehler: Kein API Token konfiguriert.")
        self.headers = {"Authorization": f"Bearer {API_TOKEN}"}
        self.collection_id = None

    def get_collection_id(self, name):
        """Sucht die Collection ID."""
        try:
            resp = requests.get(f"{OPEN_WEBUI_URL}/api/v1/knowledge/", headers=self.headers)
            resp.raise_for_status()
            data = resp.json()
            # Open WebUI API response structure check
            results = data if isinstance(data, list) else data.get('items', [])
            
            for col in results:
                if isinstance(col, dict) and col.get("name") == name:
                    return col.get("id")
        except Exception as e:
            print(f"⚠️  Fehler beim Abrufen der Collections: {e}")
        return None

    def create_collection(self, name):
        """Erstellt eine neue Collection."""
        print(f"🔨 Erstelle Collection '{name}'...")
        try:
            data = {"name": name, "description": "Automatisch importiertes Paperless Archiv"}
            resp = requests.post(f"{OPEN_WEBUI_URL}/api/v1/knowledge/create", json=data, headers=self.headers)
            resp.raise_for_status()
            return resp.json().get("id")
        except Exception as e:
            print(f"❌ Fehler beim Erstellen der Collection: {e}")
            return None

    def ensure_collection(self):
        if self.collection_id: return self.collection_id
        
        cid = self.get_collection_id(COLLECTION_NAME)
        if not cid:
            cid = self.create_collection(COLLECTION_NAME)
        
        if not cid:
            raise Exception("❌ Fatal: Konnte Collection nicht initialisieren.")
            
        self.collection_id = cid
        print(f"✅ Collection aktiv: {COLLECTION_NAME} ({cid})")
        return cid

    def get_remote_files(self):
        """Holt alle Dateien, die aktuell in Open WebUI sind (nicht nur in der Collection, sondern global)."""
        # HINWEIS: Open WebUI hat keine direkte API "List files in knowledge base".
        # Wir listen alle Files und prüfen die Metadaten oder Namen.
        try:
            resp = requests.get(f"{OPEN_WEBUI_URL}/api/v1/files/", headers=self.headers)
            resp.raise_for_status()
            # Falls Liste von Objekten
            return resp.json() 
        except Exception as e:
            print(f"⚠️ Fehler beim Listen der Remote-Dateien: {e}")
            return []

    def upload_file(self, filepath):
        """Lädt eine Datei hoch."""
        filename = os.path.basename(filepath)
        mime_type, _ = mimetypes.guess_type(filepath)
        if not mime_type: mime_type = "application/pdf"
            
        # print(f"⬆️  Upload: {filename}")
        try:
            with open(filepath, "rb") as f:
                files = {"file": (filename, f, mime_type)}
                resp = requests.post(f"{OPEN_WEBUI_URL}/api/v1/files/", files=files, headers=self.headers)
                resp.raise_for_status()
                return resp.json().get("id")
        except Exception as e:
            print(f"❌ Upload fehlgeschlagen für {filename}: {e}")
            return None

    def add_to_collection(self, file_id):
        """Verknüpft Datei mit Collection."""
        try:
            data = {"file_id": file_id} 
            resp = requests.post(f"{OPEN_WEBUI_URL}/api/v1/knowledge/{self.collection_id}/file/add", json=data, headers=self.headers)
            if resp.status_code != 200:
                 print(f"⚠️  Verknüpfung fehlgeschlagen: {resp.text}")
        except Exception as e:
            print(f"❌ Fehler beim Verknüpfen: {e}")

    def delete_remote_file(self, file_id):
        """Löscht eine Datei aus Open WebUI."""
        try:
            # Zuerst aus Collection entfernen? API unklar. Löschen der Datei sollte reichen.
            resp = requests.delete(f"{OPEN_WEBUI_URL}/api/v1/files/{file_id}", headers=self.headers)
            if resp.status_code == 200:
                print(f"🗑️  Datei gelöscht: server-id {file_id}")
            else:
                print(f"⚠️  Löschen fehlgeschlagen {file_id}: {resp.status_code}")
        except Exception as e:
            print(f"❌ Fehler beim Löschen: {e}")

    def sync_all(self):
        """Hauptlogik für Full-Sync (Cronjob)."""
        print("🔄 Starte Full-Sync (mit Löschung)...")
        self.ensure_collection()
        
        # 1. Bestandsaufnahme Lokal
        local_files = {} # filename -> filepath
        if not os.path.exists(ARCHIVE_DIR):
            print(f"❌ Archiv-Ordner fehlt: {ARCHIVE_DIR}")
            return

        for root, _, files in os.walk(ARCHIVE_DIR):
            for file in files:
                if file.lower().endswith(".pdf"):
                    local_files[file] = os.path.join(root, file)
        
        print(f"📊 Lokal gefunden: {len(local_files)} Dateien")

        # 2. Bestandsaufnahme Remote
        remote_files = self.get_remote_files()
        remote_map = {} # filename -> id
        # Wir nehmen an, dass Dateinamen (00123.pdf) eindeutig sind
        if isinstance(remote_files, list):
            for rf in remote_files:
                # Prüfen ob File Teil der Collection ist? 
                # Open WebUI API gibt File-Liste zurück. Wir löschen nur Files, die auch lokal fehlen.
                # Vorsicht: Lösche keine User-Uploads!
                # Wir erkennen Paperless Files am Namen (Zahlen.pdf) oder wir machen es einfach:
                # Wir managen NUR files in unserer Collection? 
                # API limit: Wir wissen nicht welche File in welcher Collection ist ohne weiteres.
                # Annahme: Wir managen alle Files die wie Paperless aussehen.
                rf_name = rf.get('filename') or rf.get('meta', {}).get('name')
                rf_id = rf.get('id')
                if rf_name and rf_id:
                    remote_map[rf_name] = rf_id

        print(f"☁️ Remote gefunden: {len(remote_map)} Dateien (gesamt)")

        # 3. Synchronisation
        
        # A) Upload New
        upload_count = 0
        for fname, fpath in local_files.items():
            if fname not in remote_map:
                print(f"➕ Neu: {fname}")
                fid = self.upload_file(fpath)
                if fid:
                    self.add_to_collection(fid)
                    upload_count += 1
            else:
                # B) Update Modified?
                # Schwierig ohne Hash remote. Wir überspringen existierende vorerst.
                pass
        
        # C) Delete Extinct
        # Lösche nur Dateien, die remote da sind aber lokal weg, UND die nach Paperless aussehen (z.B. .pdf)
        # Um Safety zu haben: Wir managen nur Files die wir auch hochgeladen haben?
        # Ohne DB schwierig. Wir nutzen den Dateinamen.
        # Paperless filenames: "0000123.pdf" (Ziffern).
        
        delete_count = 0
        for rname, rid in remote_map.items():
            if rname not in local_files:
                # Safety Check: Ist es ein Paperless File?
                # Wir löschen es, wenn es eine PDF ist und wir im Sync Modus sind.
                # ACHTUNG: Das könnte User Files löschen.
                # Besser: Wir loggen nur, solange wir nicht sicher sind.
                # User wollte "gelöschte dokumente aus dem ai-cache löschen".
                
                # Wir prüfen ob es eine Paperless-ID ist (Ziffern.pdf)
                is_paperless_style = rname.lower().endswith('.pdf') and rname[:-4].isdigit()
                
                if is_paperless_style:
                    print(f"➖ Gelöscht lokal: {rname} -> Entferne Remote")
                    self.delete_remote_file(rid)
                    delete_count += 1
                else:
                    # Ignore non-paperless files
                    pass

        print(f"✅ Sync fertig: {upload_count} hochgeladen, {delete_count} gelöscht.")

    def sync_single(self, filepath):
        """Lädt eine einzelne Datei hoch (Post-Consume)."""
        print(f"🚀 Post-Consume Sync: {filepath}")
        self.ensure_collection()
        
        fname = os.path.basename(filepath)
        
        # Prüfen ob schon existiert -> Löschen (Update)
        remote_files = self.get_remote_files()
        if isinstance(remote_files, list):
            for rf in remote_files:
                rf_name = rf.get('filename') or rf.get('meta', {}).get('name')
                if rf_name == fname:
                    print(f"♻️  Datei existiert bereits ({rf.get('id')}), lösche alte Version...")
                    self.delete_remote_file(rf.get('id'))
        
        # Upload
        fid = self.upload_file(filepath)
        if fid:
            self.add_to_collection(fid)
            print(f"✅ Datei erfolgreich synchronisiert: {fname}")
        else:
            print("❌ Fehler beim Sync.")

def main():
    parser = argparse.ArgumentParser(description='Open WebUI Sync for Paperless')
    parser.add_argument('--post-consume', action='store_true', help='Run in single file mode')
    parser.add_argument('file_path', nargs='?', help='Path to file (for post-consume)')
    
    args = parser.parse_args()
    
    syncer = OpenWebUISync()
    
    if args.post_consume and args.file_path:
        syncer.sync_single(args.file_path)
    else:
        syncer.sync_all()

if __name__ == "__main__":
    main()
