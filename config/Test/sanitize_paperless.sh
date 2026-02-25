#!/bin/bash

# --- KONFIGURATION ---
# Pfad zum Media-Ordner von Paperless
MEDIA_PATH="/volume1/docker/paperless-ngx/media/documents"
# Wohin sollen die fehlerhaften Dateien verschoben werden?
EXPORT_PATH="/volume1/docker/paperless-ngx/media/corrupt_docs"
# Name der Logdatei
LOG_FILE="sanity_fix.log"

# Erstelle Export-Ordner, falls nicht vorhanden
mkdir -p "$EXPORT_PATH"

echo "[$(date)] Starte Sanity Scan..." | tee -a "$LOG_FILE"

# Führe den Sanity Check aus und filtere Zeilen, die Pfade zu Dateien enthalten
# Wir suchen nach typischen Fehlermeldungen wie "Checksum mismatch" oder "File not found"
python3 manage.py document_sanity_checker 2>&1 | grep -E "documents/orig/.*" | while read -r line; do
    
    # Extrahiere den Dateipfad aus der Fehlermeldung
    # Dies setzt voraus, dass der Pfad mit 'documents/orig/' beginnt
    FILE_PATH=$(echo "$line" | grep -oP 'documents/orig/[^ ]+')
    FULL_PATH="$MEDIA_PATH/../$FILE_PATH"

    if [ -f "$FULL_PATH" ]; then
        echo "Gefunden: $FILE_PATH - Verschiebe nach $EXPORT_PATH" | tee -a "$LOG_FILE"
        mv "$FULL_PATH" "$EXPORT_PATH/"
    else
        echo "Fehler: Datei $FILE_PATH wurde im Log erwähnt, existiert aber nicht physisch." | tee -a "$LOG_FILE"
    fi
done

echo "[$(date)] Scan beendet." | tee -a "$LOG_FILE"