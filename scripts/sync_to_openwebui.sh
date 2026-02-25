#!/bin/bash
# ─────────────────────────────────────────────────────────────
# sync_to_openwebui.sh
# Hilfs-Script: Listet alle PDFs im Archiv-Ordner auf, die in
# Open WebUI als Knowledge Collection importiert werden können.
#
# Nutzung:
#   1. Open WebUI öffnen → Admin → Knowledge → Neue Collection
#   2. Collection "Paperless Archiv" erstellen
#   3. PDFs per Drag & Drop hochladen ODER dieses Script nutzen
#
# Hinweis: Open WebUI hat den Ordner /paperless-archive gemountet.
# Die PDFs können direkt aus diesem Ordner referenziert werden.
# ─────────────────────────────────────────────────────────────

ARCHIVE_DIR="/volume1/docker/paperless-ngx/media/archive"
OPEN_WEBUI_URL="http://localhost:8501"

echo "═══════════════════════════════════════════════════"
echo "  Paperless Archiv → Open WebUI Knowledge Sync"
echo "═══════════════════════════════════════════════════"
echo ""

# Zähle PDFs
PDF_COUNT=$(find "$ARCHIVE_DIR" -name "*.pdf" -type f 2>/dev/null | wc -l)
echo "📂 Archiv-Ordner: $ARCHIVE_DIR"
echo "📄 Gefundene PDFs: $PDF_COUNT"
echo ""

if [ "$PDF_COUNT" -eq 0 ]; then
    echo "⚠️  Keine PDFs im Archiv gefunden."
    exit 0
fi

echo "Die neuesten 20 Dokumente:"
echo "──────────────────────────────────────────────────"
find "$ARCHIVE_DIR" -name "*.pdf" -type f -printf '%T@ %p\n' 2>/dev/null \
    | sort -rn \
    | head -20 \
    | while read -r timestamp filepath; do
        filename=$(basename "$filepath")
        size=$(du -h "$filepath" 2>/dev/null | cut -f1)
        date=$(date -d "@${timestamp%.*}" '+%Y-%m-%d %H:%M' 2>/dev/null)
        echo "  📄 $filename ($size, $date)"
    done

echo ""
echo "──────────────────────────────────────────────────"
echo ""
echo "📋 Nächste Schritte:"
echo "  1. Öffne Open WebUI: $OPEN_WEBUI_URL"
echo "  2. Gehe zu: Workspace → Knowledge → + Neue Collection"
echo "  3. Erstelle Collection 'Paperless Archiv'"
echo "  4. Lade die gewünschten PDFs hoch"
echo ""
echo "💡 Tipp: Open WebUI hat den Archiv-Ordner unter"
echo "   /paperless-archive (readonly) gemountet."
echo "   Du kannst auch über die API Dateien importieren."
echo ""
