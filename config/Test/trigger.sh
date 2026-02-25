#!/bin/bash
# Paperless übergibt Umgebungsvariablen automatisch
# Wir filtern nach dem Tag 'KI-OCR' (ID muss in Paperless nachgeschlagen werden oder Name matchen)
if [[ "$DOCUMENT_TAGS" == *"KI-OCR"* ]]; then
    /home/heiko/ki-ocr/venv/bin/python3 /home/heiko/ki-ocr/process_by_tag.py "$DOCUMENT_ID" "$DOCUMENT_SOURCE_PATH"
fi
