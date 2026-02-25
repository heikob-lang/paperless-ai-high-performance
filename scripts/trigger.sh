#!/bin/bash
# Check auf Tag-ID (z.B. 15 für 'KI-OCR')
if [[ ",$DOCUMENT_TAGS," == *",15,"* ]]; then
    /usr/bin/python3 /usr/src/paperless/scripts/process_by_tag.py "$DOCUMENT_ID" "$DOCUMENT_SOURCE_PATH"
fi
