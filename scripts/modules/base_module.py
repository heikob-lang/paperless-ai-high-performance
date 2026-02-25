"""
Base class for all AI modules.
"""
from abc import ABC, abstractmethod
from typing import Dict, Any

class BaseModule(ABC):
    def __init__(self, config: Dict[str, Any], paperless_client, ollama_client):
        self.config = config
        self.paperless = paperless_client
        self.ollama = ollama_client

    @abstractmethod
    def process(self, document_id: int, file_path: str, document_data: Dict[str, Any]) -> None:
        """
        Process the document.
        :param document_id: The ID of the document in Paperless.
        :param file_path: Absolute path to the original file.
        :param document_data: Metadata of the document from Paperless API.
        """
        pass
