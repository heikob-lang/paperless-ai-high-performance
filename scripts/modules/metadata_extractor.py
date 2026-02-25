from .base_module import BaseModule
from typing import Dict, Any
import json
import datetime
import requests

class MetadataExtractor(BaseModule):
    def process(self, document_id: int, file_path: str, document_data: Dict[str, Any]) -> None:
        if not self.config['modules']['metadata_extractor'].get('enabled', False):
            return

        print(f"Running Metadata Extraction for {document_id}")
        
        content = document_data.get('content', '')
        if not content:
            return

        # Prompt für LLM (Optimiert für deutsche Dokumente & Formate) laden
        base_prompt = self.config.get('prompts', {}).get(
            'metadata_extraction_text', 
            "Lese Metadaten aus Text als JSON.\n\nDokumenttext (Auszug):\n"
        )
        prompt = f"{base_prompt}\n{content[:4000]}"

        response_text = self.ollama.generate(prompt, format="json")
        
        try:
            # Da wir format="json" erzwingen, sollte die Antwort valides JSON sein.
            # Zur Sicherheit behalten wir den Extraktions-Block, reduzieren ihn aber.
            json_str = response_text.strip()
            
            # Ollama liefert manchmal noch Markdown drumherum, auch mit JSON mode
            if json_str.startswith('```json'):
                json_str = json_str.replace('```json', '', 1)
            if json_str.endswith('```'):
                json_str = json_str.rsplit('```', 1)[0]
                
            start_idx = json_str.find('{')
            end_idx = json_str.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = json_str[start_idx:end_idx+1]
            else:
                print("FEHLER: Kein {} Block in der JSON-Response gefunden.")
                return

            metadata = json.loads(json_str)
            print(f"LLM extracted: {metadata}")
            
            updates = {}
            
            # 1. Titel setzen
            if metadata.get('title'):
                updates['title'] = metadata['title']
                
            # 2. Datum setzen
            if metadata.get('created'):
                try:
                    datetime.datetime.strptime(metadata['created'], '%Y-%m-%d')
                    updates['created'] = metadata['created']
                except ValueError:
                    pass

            # 3. Korrespondent zuordnen (via API: suchen oder erstellen)
            correspondent_name = metadata.get('correspondent', '').strip()
            if correspondent_name:
                corr_id = self._get_or_create_correspondent(correspondent_name)
                if corr_id:
                    updates['correspondent'] = corr_id
                    print(f"✅ Correspondent '{correspondent_name}' -> ID {corr_id}")

            # 4. Tags zuordnen
            tag_names = metadata.get('tags', [])
            if tag_names and isinstance(tag_names, list):
                tag_ids = []
                for tag_name in tag_names:
                    tag_id = self._get_or_create_tag(tag_name.strip())
                    if tag_id:
                        tag_ids.append(tag_id)
                
                if tag_ids:
                    # Frische Tags vom API holen (nicht document_data, das könnte veraltet sein)
                    fresh_doc = self.paperless.get_document(document_id)
                    existing_tags = fresh_doc.get('tags', []) if fresh_doc else document_data.get('tags', [])
                    merged_tags = list(set(existing_tags + tag_ids))
                    updates['tags'] = merged_tags
                    print(f"✅ Tags: {tag_names} -> IDs {tag_ids}")

            # 5. Dokumenttyp zuordnen
            doc_type_name = metadata.get('document_type', '').strip()
            if doc_type_name:
                dt_id = self._get_or_create_document_type(doc_type_name)
                if dt_id:
                    updates['document_type'] = dt_id
                    print(f"✅ Document Type '{doc_type_name}' -> ID {dt_id}")

            # Updates anwenden
            if updates:
                print(f"Updating metadata: {updates}")
                self.paperless.update_document(document_id, updates)

        except json.JSONDecodeError:
            print(f"Error parsing LLM response: {response_text[:500]}")
        except Exception as e:
            print(f"Error in MetadataExtractor: {e}")

    def _get_or_create_correspondent(self, name: str) -> int | None:
        """Sucht einen Korrespondenten nach Name. Erstellt ihn, falls nicht vorhanden."""
        try:
            url = f"{self.paperless.api_url}/correspondents/?name__iexact={name}"
            resp = requests.get(url, headers=self.paperless.headers)
            if resp.status_code == 200:
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                
                # Nicht gefunden -> erstellen
                create_resp = requests.post(
                    f"{self.paperless.api_url}/correspondents/",
                    headers=self.paperless.headers,
                    json={"name": name}
                )
                if create_resp.status_code in (200, 201):
                    new_id = create_resp.json().get('id')
                    print(f"Created new correspondent: '{name}' (ID: {new_id})")
                    return new_id
        except Exception as e:
            print(f"Error with correspondent '{name}': {e}")
        return None

    def _get_or_create_tag(self, name: str) -> int | None:
        """Sucht einen Tag nach Name. Erstellt ihn, falls nicht vorhanden."""
        try:
            url = f"{self.paperless.api_url}/tags/?name__iexact={name}"
            resp = requests.get(url, headers=self.paperless.headers)
            if resp.status_code == 200:
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                
                # Nicht gefunden -> erstellen
                create_resp = requests.post(
                    f"{self.paperless.api_url}/tags/",
                    headers=self.paperless.headers,
                    json={"name": name, "is_inbox_tag": False}
                )
                if create_resp.status_code in (200, 201):
                    new_id = create_resp.json().get('id')
                    print(f"Created new tag: '{name}' (ID: {new_id})")
                    return new_id
        except Exception as e:
            print(f"Error with tag '{name}': {e}")
        return None

    def _get_or_create_document_type(self, name: str) -> int | None:
        """Sucht einen Dokumenttyp nach Name. Erstellt ihn, falls nicht vorhanden."""
        try:
            url = f"{self.paperless.api_url}/document_types/?name__iexact={name}"
            resp = requests.get(url, headers=self.paperless.headers)
            if resp.status_code == 200:
                results = resp.json().get('results', [])
                if results:
                    return results[0]['id']
                
                # Nicht gefunden -> erstellen
                create_resp = requests.post(
                    f"{self.paperless.api_url}/document_types/",
                    headers=self.paperless.headers,
                    json={"name": name}
                )
                if create_resp.status_code in (200, 201):
                    new_id = create_resp.json().get('id')
                    print(f"Created new document type: '{name}' (ID: {new_id})")
                    return new_id
        except Exception as e:
            print(f"Error with document type '{name}': {e}")
        return None


    def extract_text_from_images(self, images_b64: list[str]) -> str:
        """Extrahiert Text aus Bildern via Vision LLM (OCR)."""
        full_text = []
        
        prompt = self.config.get('prompts', {}).get(
            'ocr_base',
            "Erkenne den Text exakt."
        )

        for i, b64 in enumerate(images_b64):
            print(f"Extrating text from page {i+1} via Vision LLM...")
            text = self.ollama.generate(prompt, images=[b64])
            if text:
                full_text.append(text)
            else:
                full_text.append(f"[OCR Fehler Seite {i+1}]")
        
        return "\n\n".join(full_text)

    def extract_metadata_from_image(self, image_b64: str) -> dict:
        """Extrahiert Metadaten direkt aus dem Bild der ersten Seite."""
        prompt = self.config.get('prompts', {}).get(
            'metadata_extraction_image',
            "Analysiere das Bild und liefere Metadaten als JSON (title, created, correspondent, tags, document_type)."
        )
        
        response_text = self.ollama.generate(prompt, images=[image_b64], format="json")
        
        try:
            # Robust JSON extraction (wie oben, mit Markdown-Cleanup)
            json_str = response_text.strip()
            if json_str.startswith('```json'):
                json_str = json_str.replace('```json', '', 1)
            if json_str.endswith('```'):
                json_str = json_str.rsplit('```', 1)[0]
                
            start_idx = json_str.find('{')
            end_idx = json_str.rfind('}')
            
            if start_idx != -1 and end_idx != -1:
                json_str = json_str[start_idx:end_idx+1]

            metadata = json.loads(json_str)
            print(f"Vision LLM extracted: {metadata}")
            return metadata
        except json.JSONDecodeError:
            print(f"Error parsing Vision LLM response: {response_text[:200]}")
            return {}
        except Exception as e:
            print(f"Error in Vision Metadata Extraction: {e}")
            return {}
