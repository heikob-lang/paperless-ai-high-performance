#!/bin/bash

# --- KONFIGURATION ---
PAPERLESS_URL="http://172.18.0.6:8000"
API_TOKEN="2051eaf6a446d1bbb6a034588604ac9a5e20b1ee"
TARGET_TAG_ID=960
CONTAINER_NAME="paperless-webserver-1" # Falls dein Container anders heißt, anpassen
# ---------------------

echo "Starte Sanity Checker und Suche nach Fehlern..."

# 1. IDs extrahieren
MAP_IDS=$(docker exec -t "$CONTAINER_NAME" python3 manage.py document_sanity_checker 2>&1 \
    | grep -oP 'document #\K[0-9]+' \
    | sort -u)

if [ -z "$MAP_IDS" ]; then
    echo "Keine fehlerhaften Dokumente gefunden."
    exit 0
fi

for DOC_ID in $MAP_IDS; do
    echo "Verarbeite Dokument #$DOC_ID..."

    # Aktuelle Dokumentdaten abrufen
    DOC_DATA=$(curl -s -H "Authorization: Token $API_TOKEN" "$PAPERLESS_URL/api/documents/$DOC_ID/")
    
    # Aktuelle Tags extrahieren
    CURRENT_TAGS=$(echo "$DOC_DATA" | jq -r '.tags[]')

    # Prüfen, ob das Tag schon existiert
    if echo "$CURRENT_TAGS" | grep -q "^$TARGET_TAG_ID$"; then
        echo "Tag $TARGET_TAG_ID ist bereits gesetzt. Überspringe."
        continue
    fi

    # Neues Tag-Array bauen
    NEW_TAGS_JSON=$(echo -e "$CURRENT_TAGS\n$TARGET_TAG_ID" | jq -R . | jq -s -c .)

    # PATCH ausführen und HTTP-Statuscode speichern
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X PATCH "$PAPERLESS_URL/api/documents/$DOC_ID/" \
        -H "Authorization: Token $API_TOKEN" \
        -H "Content-Type: application/json" \
        -d "{\"tags\": $NEW_TAGS_JSON}")

    if [ "$HTTP_CODE" -eq 200 ]; then
        echo "Erfolg: Dokument #$DOC_ID getaggt."
    else
        echo "FEHLER: API meldet Status $HTTP_CODE für Dokument #$DOC_ID."
    fi
done

echo "Vorgang abgeschlossen."
