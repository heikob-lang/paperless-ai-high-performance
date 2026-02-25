import requests
from typing import Dict, Any, Optional

class PaperlessClient:
    def __init__(self, config: Dict[str, Any]):
        self.api_url = config['paperless']['url'].rstrip('/')
        self.token = config['paperless']['token']
        self.headers = {"Authorization": f"Token {self.token}"}
        # Public URL for user-facing links (fallback to internal URL if not set)
        self.public_url = config['paperless'].get('public_url', self.api_url).rstrip('/')

    def get_document_link(self, doc_id: int) -> str:
        """Generate a public link to the document."""
        return f"{self.public_url}/documents/{doc_id}/details"

    def get_comparison_link(self, original_id: int, duplicate_id: int) -> str:
        """Generate a link to the side-by-side comparison tool."""
        # Using static/compare.html (gemountet via docker-compose) relative to public_url
        return f"{self.public_url}/static/compare.html?left={original_id}&right={duplicate_id}"

    def get_document_metadata(self, document_id: int) -> Dict[str, Any]:
        """Holt detaillierte Metadaten eines Dokuments."""
        try:
            response = self.session.get(f"{self.api_url}/documents/{document_id}/metadata/")
            if response.status_code == 200:
                return response.json()
            return {}
        except Exception as e:
            print(f"Error fetching metadata for {document_id}: {e}")
            return {}

    def download_document(self, document_id: int, target_path: Path) -> bool:
        """Lädt das Original-PDF eines Dokuments herunter."""
        try:
            response = self.session.get(f"{self.api_url}/documents/{document_id}/download/", stream=True)
            if response.status_code == 200:
                with open(target_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                return True
            print(f"Download failed for {document_id}: HTTP {response.status_code}")
            return False
        except Exception as e:
            print(f"Error downloading document {document_id}: {e}")
            return False

    def get_tag_id_by_name(self, tag_name: str) -> Optional[int]:
        """Sucht die ID eines Tags anhand des Namens."""
        try:
            url = f"{self.api_url}/tags/?name__iexact={tag_name}"
            response = self.session.get(url)
            if response.status_code == 200:
                results = response.json().get('results', [])
                if results:
                    return results[0].get('id')
            return None
        except Exception as e:
            print(f"Error finding tag {tag_name}: {e}")
            return None

    def add_tag(self, document_id: int, tag_name: str):
        """Fügt einem Dokument ein Tag hinzu (falls noch nicht vorhanden)."""
        tag_id = self.get_tag_id_by_name(tag_name)
        if not tag_id:
            # Erstellen falls nicht existiert
            try:
                # Standardfarbe rot für AI-OCR
                res = self.session.post(f"{self.api_url}/tags/", json={"name": tag_name, "color": "#ff0000"})
                if res.status_code == 201:
                    tag_id = res.json().get('id')
            except: pass
        
        if tag_id:
            try:
                # Aktuelle Dokumentdaten holen
                doc_res = self.session.get(f"{self.api_url}/documents/{document_id}/")
                if doc_res.status_code == 200:
                    doc_data = doc_res.json()
                    tags = doc_data.get('tags', [])
                    if tag_id not in tags:
                        tags.append(tag_id)
                        self.session.patch(f"{self.api_url}/documents/{document_id}/", json={"tags": tags})
            except Exception as e:
                print(f"Error adding tag to {document_id}: {e}")

    def remove_tag(self, document_id: int, tag_name: str):
        """Entfernt ein Tag von einem Dokument."""
        tag_id = self.get_tag_id_by_name(tag_name)
        if tag_id:
            try:
                doc_res = self.session.get(f"{self.api_url}/documents/{document_id}/")
                if doc_res.status_code == 200:
                    doc_data = doc_res.json()
                    tags = doc_data.get('tags', [])
                    if tag_id in tags:
                        tags.remove(tag_id)
                        self.session.patch(f"{self.api_url}/documents/{document_id}/", json={"tags": tags})
            except Exception as e:
                print(f"Error removing tag from {document_id}: {e}")

    def get_document(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Fetch document metadata by ID."""
        try:
            response = requests.get(f"{self.api_url}/documents/{doc_id}/", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching document {doc_id}: {e}")
            return None

    def update_document(self, doc_id: int, updates: Dict[str, Any]) -> bool:
        """Update document metadata (tags, correspondent, etc.)."""
        try:
            response = requests.patch(f"{self.api_url}/documents/{doc_id}/", headers=self.headers, json=updates)
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Error updating document {doc_id}: {e}")
            return False

    def add_note(self, doc_id: int, note: str) -> bool:
        """Add a note to the document."""
        try:
            payload = {
                "note": note
            }
            response = requests.post(
                f"{self.api_url}/documents/{doc_id}/notes/",
                headers=self.headers,
                json=payload
            )
            response.raise_for_status()
            return True
        except requests.RequestException as e:
            print(f"Error adding note to document {doc_id}: {e}")
            return False

    def get_document_content(self, doc_id: int) -> str:
        """Fetch the OCR content of the document."""
        try:
            doc = self.get_document(doc_id)
            if doc:
                return doc.get('content', '')
            return ""
        except Exception:
            return ""

    def search_documents(self, query: str) -> list[dict]:
        """Search for documents using the Paperless API."""
        try:
            # Paperless API search endpoint: /api/documents/?query=...
            params = {"query": query, "page_size": 10}
            response = requests.get(f"{self.api_url}/documents/", headers=self.headers, params=params)
            print(f"DEBUG: Search URL: {response.url}")
            print(f"DEBUG: Search Status: {response.status_code}")
            try:
                data = response.json()
                # print(f"DEBUG: Search Response: {data}") 
                return data.get('results', [])
            except ValueError:
                print(f"DEBUG: Invalid JSON response: {response.text}")
                return []
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"Error searching documents: {e}")
            return []

    def get_document_by_checksum(self, checksum: str) -> Optional[Dict[str, Any]]:
        """Fetch document by MD5 checksum to detect binary duplicates."""
        try:
            # Paperless API does NOT support ?checksum=... filtering directly.
            # We must use the global search query with the checksum prefix.
            params = {"query": f"checksum:{checksum}"}
            response = requests.get(f"{self.api_url}/documents/", headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            results = data.get('results', [])
            
            # Additional safety: search might return partial matches (though unlikely for hashes)
            for res in results:
                if res.get('checksum') == checksum:
                    return res
                    
            return None
        except requests.RequestException as e:
            print(f"Error checking checksum {checksum}: {e}")
            return None

    def get_document_metadata(self, doc_id: int) -> Optional[Dict[str, Any]]:
        """Fetch true storage path metadata to verify physical existence (Zombie Check)"""
        try:
            response = requests.get(f"{self.api_url}/documents/{doc_id}/metadata/", headers=self.headers)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"Error fetching metadata for document {doc_id}: {e}")
            return None
