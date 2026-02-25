from .base_module import BaseModule
from typing import Dict, Any

class ContentEnhancer(BaseModule):
    def process(self, document_id: int, file_path: str, document_data: Dict[str, Any]) -> None:
        if not self.config['modules']['content_enhancer'].get('enabled', False):
            return

        print(f"Running Content Enhancer for {document_id}")
        
        content = document_data.get('content', '')
        if not content:
            return

        # 1. Summarization
        # or "Super-OCR" cleanup
        
        base_prompt = self.config.get('prompts', {}).get(
            'content_summary', 
            "Fasse dieses Dokument zusammen:\n"
        )
        prompt = f"{base_prompt}\n{content[:6000]}"
        print(f"Generating summary using model: {self.ollama.summary_model}")
        summary = self.ollama.generate(prompt, model=self.ollama.summary_model)
        
        if summary:
            # Append summary to notes
            note_content = f"--- AI Summary ---\n{summary}"
            self.paperless.add_note(document_id, note_content)
            print(f"Added summary to document {document_id}")

        # 2. Add "Clean Content" to a custom field or similar?
        # Paperless doesn't have a "Clean Content" field by default. 
        # Modifying 'content' field directly is usually overwritten by re-OCR.
        # Best approach: Put refined text in a Note or specific Custom Field "AI_Content"
