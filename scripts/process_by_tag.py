import sys
import os
import subprocess
import time
from datetime import datetime
from typing import Any, TYPE_CHECKING
import yaml

# Mock Class for Linter/Runtime Safety
class MockModule:
    def __getattr__(self, _) -> Any: return MockModule()
    def __call__(self, *args, **kwargs) -> Any: return MockModule()
    def __enter__(self) -> Any: return MockModule()
    def __exit__(self, *args) -> Any: return None
    def __getitem__(self, _) -> Any: return MockModule()
    def __iter__(self) -> Any: return iter([])
    def __len__(self) -> int: return 0
    def __bool__(self) -> bool: return False

# Safe Imports
# Safe Imports
if TYPE_CHECKING:
    requests: Any = MockModule()
    fitz: Any = MockModule()
    Client: Any = MockModule()
else:
    try:
        import requests
        import fitz
        from ollama import Client
    except ImportError:
        requests = MockModule()
        fitz = MockModule()
        Client = MockModule()

# --- KONFIGURATION (DOCKER-OPTIMIERT) ---
OLLAMA_CLIENT = Client(host='http://host.docker.internal:11434', timeout=300.0)
MODEL = "deepseek-ocr:3b"

# Paperless API Details
API_URL = "http://localhost:8000/api"
API_TOKEN = "2051eaf6a446d1bbb6a034588604ac9a5e20b1ee"
HEADERS = {"Authorization": f"Token {API_TOKEN}"}

# Verzeichnis für temporäre Dateien im Container
TEMP_DIR = "/usr/src/paperless/media/temp_ki_ocr"

def ensure_temp_dir():
    """Prüft ob das Temp-Verzeichnis existiert, andernfalls erstellen"""
    if not os.path.exists(TEMP_DIR):
        try:
            os.makedirs(TEMP_DIR, exist_ok=True)
            # Berechtigungen setzen, damit der User 'paperless' schreiben darf
            os.chmod(TEMP_DIR, 0o775)
            print(f"Verzeichnis erstellt: {TEMP_DIR}")
        except Exception as e:
            print(f"Fehler beim Erstellen des Verzeichnisses {TEMP_DIR}: {e}")
            sys.exit(1)

def get_ki_data(file_path):
    """Extrahiert Titel und korrigierten Text via KI"""
    try:
        doc = fitz.open(file_path)
    except Exception as e:
        return None, f"Fehler beim Öffnen: {e}"

    full_text: list[str] = []
    titel_vorschlag: str = "KI-Dokument"
    
    for i in range(min(2, len(doc))):
        page = doc[i]
        pix = page.get_pixmap(matrix=fitz.Matrix(1.2, 1.2))
        img_bytes = pix.tobytes("png")
        
        # Config laden für Prompt
        config = {}
        config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'ai_config.yaml')
        if os.path.exists(config_path):
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)

        base_prompt = config.get('prompts', {}).get(
            'tag_processing',
            "Analysiere dieses Dokument:\n{text}\n"
        )
        prompt = base_prompt.format(text="Bitte extrahiere den Text und einen Titel in der ersten Zeile.")
        
        try:
            response = OLLAMA_CLIENT.generate(model=MODEL, prompt=prompt, images=[img_bytes])
            output = response.get('response', '')
            lines = output.strip().split('\n')
            
            if i == 0 and lines:
                titel_vorschlag = lines[0].replace('#', '').strip()
                full_text.append("\n".join(lines[1:]))
            else:
                full_text.append(output)
            
            OLLAMA_CLIENT.generate(model=MODEL, keep_alive=0)
        except Exception as e:
            print(f"KI-Fehler auf Seite {i}: {e}")

    doc.close()
    return titel_vorschlag, "\n\n".join(full_text)

def process_document(doc_id, source_path):
    ensure_temp_dir() # Sicherstellen, dass der Pfad existiert
    
    print(f"--- Starte KI-Veredelung für Dokument ID {doc_id} ---")
    temp_sidecar = os.path.join(TEMP_DIR, f"{doc_id}.txt")
    temp_output_pdf = os.path.join(TEMP_DIR, f"output_{doc_id}.pdf")
    
    try:
        # 1. KI-Analyse
        titel, text = get_ki_data(source_path)
        with open(temp_sidecar, "w", encoding="utf-8") as f:
            f.write(text)

        # 2. OCRmyPDF
        subprocess.run([
            "ocrmypdf", "--force-ocr", "--output-type", "pdf",
            "--pdf-renderer", "sandwich", "--optimize", "1",
            "--sidecar", temp_sidecar, "-l", "deu",
            source_path, temp_output_pdf
        ], check=True)

        # 3. Metadaten Update
        requests.patch(f"{API_URL}/documents/{doc_id}/", headers=HEADERS, json={
            "title": titel,
            "notes": [{"note": f"KI-OCR Veredelung abgeschlossen am 25.01.2026 (Modell: {MODEL})"}]
        })

        # 4. Datei ersetzen
        with open(temp_output_pdf, 'rb') as f:
            requests.post(f"{API_URL}/documents/{doc_id}/update_file/", headers=HEADERS, files={'document': f})
        
        print(f"Dokument {doc_id} erfolgreich aktualisiert.")

        # 5. Speichern in Vektor-DB für Dupletten-Check
        try:
            sys.path.append(os.path.dirname(os.path.abspath(__file__)))
            try:
                from ai_processor import AIProcessor # type: ignore
            except ImportError:
                print("⚠️ Could not import AIProcessor - Duplicate detection database update failed.")
                AIProcessor = None # type: ignore

            if AIProcessor:
                ai = AIProcessor()
                # Metadaten konstruieren (Datum versuchen aus Titel zu parsen oder heute)
                meta = {
                    "title": titel,
                    "created": datetime.today().strftime('%Y-%m-%d'), # Fallback
                    "tags": ["processed_by_script"]
                }
                ai.store_document(doc_id, text, meta)
        except Exception as db_e:
            print(f"⚠️ Vektor-DB Speicherfehler: {db_e}")

    except Exception as e:
        print(f"KRITISCHER FEHLER: {e}")
    finally:
        # Aufräumen
        for tmp_file in [temp_sidecar, temp_output_pdf]:
            if os.path.exists(tmp_file):
                os.remove(tmp_file)

if __name__ == "__main__":
    if len(sys.argv) > 2:
        process_document(sys.argv[1], sys.argv[2])
    else:
        print("Argumente fehlen: ID und Pfad benötigt.")
