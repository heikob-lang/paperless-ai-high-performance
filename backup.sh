#!/bin/bash
# Paperless AI Workflow - Backup
# Erstellt eine komprimierte Sicherung aller Container-Daten, Datenbanken und Konfigurationen

BACKUP_DIR="./backups"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
BACKUP_FILE="$BACKUP_DIR/paperless_ai_backup_$DATE.tar.gz"

echo "=========================================="
echo "📦 Paperless AI - Backup"
echo "=========================================="

mkdir -p "$BACKUP_DIR"

echo "[1] Stoppe Container für ein inkonsistenzfreies Backup..."
docker compose stop

echo "[2] Sammle Ordner (Media, Postgres, ChromaDB, Skripte)..."
# Wir sichern alle relevanten Ordner und Configs
DIRECTORIES="docker-compose.yaml scripts dashboard media data pgdata chromadb_data"

if [ -d "open-webui_data" ]; then DIRECTORIES="$DIRECTORIES open-webui_data"; fi
if [ -d "scan_input" ]; then DIRECTORIES="$DIRECTORIES scan_input"; fi

echo "[3] Komprimiere Dateien (Dies kann bei vielen PDF/A-Dokumenten dauern)..."
# -c: create, -z: gzip, -v: verbose (in file, not on screen to avoid lag), -f: file
tar -czf "$BACKUP_FILE" $DIRECTORIES

echo "[4] Starte Container wieder..."
docker compose start

echo ""
echo "✅ Backup erfolgreich erstellt: $BACKUP_FILE"
echo "Größe: $(du -hm "$BACKUP_FILE" | cut -f1) MB"
