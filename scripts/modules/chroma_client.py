"""
ChromaDB Client für Paperless AI
Verwaltet Dokument-Embeddings für Duplikat-Erkennung und RAG-Chat.
"""
import os
import requests
from typing import Dict, Any, Optional, List

# ChromaDB Python Client
import chromadb
from chromadb.config import Settings


# Ollama Embedding Konfiguration aus ai_config.yaml geladen via LLMClient
COLLECTION_NAME = "paperless_documents"


class ChromaClient:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialisiert die ChromaDB-Verbindung."""
        chroma_host = os.environ.get("CHROMADB_HOST", "http://chromadb:8000")
        
        # Parse host und port
        host_parts = chroma_host.replace("http://", "").replace("https://", "").split(":")
        host = host_parts[0]
        port = int(host_parts[1]) if len(host_parts) > 1 else 8000
        
        self.client = chromadb.HttpClient(host=host, port=port)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"}  # Kosinus-Ähnlichkeit
        )
        
        # LLMClient für Embeddings initialisieren
        if config is None:
            # Fallback, falls keine config übergeben wurde
            import yaml
            from pathlib import Path
            config_path = Path(__file__).parent.parent / "ai_config.yaml"
            with open(config_path, 'r') as f:
                config = yaml.safe_load(f)
        
        # Importiere hier, um Zirkelbezüge zu vermeiden
        from .llm_client import LLMClient
        self.llm_client = LLMClient(config)
        
    def _get_embedding(self, text: str) -> List[float]:
        """Erzeugt ein Embedding via Ollama nomic-embed-text."""
        # Text kürzen für Embedding (max ~8000 Tokens)
        if not text:
            return []
        text = str(text)[:8000] # type: ignore
        
        return self.llm_client.generate_embedding(text)

    def add_document(self, doc_id: int, content: str, metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Fügt ein Dokument mit Embedding in ChromaDB ein."""
        if not content or len(content) < 50:
            print(f"Dokument {doc_id}: Zu wenig Inhalt für Embedding")
            return False
            
        embedding = self._get_embedding(content)
        if not embedding:
            print(f"Dokument {doc_id}: Embedding-Erzeugung fehlgeschlagen")
            return False
        
        # Metadata bereinigen (ChromaDB akzeptiert nur str, int, float, bool)
        clean_meta: Dict[str, Any] = {"doc_id": int(doc_id)}
        if metadata:
            for k, v in metadata.items():
                if isinstance(v, (str, int, float, bool)):
                    clean_meta[k] = v
        
        try:
            self.collection.upsert(
                ids=[str(doc_id)],
                embeddings=[embedding],
                documents=[str(content)[:5000]],  # ChromaDB speichert auch Text # type: ignore
                metadatas=[clean_meta]
            )
            print(f"✅ ChromaDB: Dokument {doc_id} indexiert ({len(embedding)} dims)")
            return True
        except Exception as e:
            print(f"ChromaDB upsert Error: {e}")
            return False

    def find_similar(self, content: str, threshold: float = 0.85, 
                     exclude_id: Optional[int] = None, n_results: int = 5) -> List[Dict[str, Any]]:
        """Sucht ähnliche Dokumente via Embedding-Vergleich."""
        embedding = self._get_embedding(content)
        if not embedding:
            return []
        
        try:
            results = self.collection.query(
                query_embeddings=[embedding],
                n_results=n_results,
                include=["metadatas", "distances", "documents"]
            )
            
            similar = []
            if results and results['ids'] and results['ids'][0]:
                for i, doc_id_str in enumerate(results['ids'][0]):
                    # ChromaDB gibt Distanz zurück, nicht Ähnlichkeit
                    # Bei cosine: similarity = 1 - distance
                    distance = results['distances'][0][i]
                    similarity = 1.0 - distance
                    
                    doc_id = int(doc_id_str)
                    
                    # Sich selbst ausschließen
                    if exclude_id and doc_id == exclude_id:
                        continue
                    
                    if similarity >= threshold:
                        similar.append({
                            "id": doc_id,
                            "similarity": similarity,
                            "metadata": results['metadatas'][0][i] if results['metadatas'] else {},
                            "content_preview": (str(results['documents'][0][i])[:4000] # type: ignore 
                                              if results['documents'] else "")
                        })
            
            return similar
            
        except Exception as e:
            print(f"ChromaDB query Error: {e}")
            return []

    def delete_document(self, doc_id: int) -> bool:
        """Löscht ein Dokument aus ChromaDB."""
        try:
            self.collection.delete(ids=[str(doc_id)])
            print(f"🗑️ ChromaDB: Dokument {doc_id} gelöscht")
            return True
        except Exception as e:
            print(f"ChromaDB delete Error: {e}")
            return False

    def get_all_doc_ids(self) -> List[int]:
        """Gibt alle gespeicherten Dokument-IDs zurück."""
        try:
            result = self.collection.get(include=[])
            return [int(id_str) for id_str in result['ids']]
        except Exception as e:
            print(f"ChromaDB get_all Error: {e}")
            return []

    def count(self) -> int:
        """Gibt die Anzahl der indexierten Dokumente zurück."""
        try:
            return self.collection.count()
        except Exception:
            return 0
