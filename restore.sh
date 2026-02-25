#!/bin/bash
# Paperless AI Workflow - Restore
# Stellt ein Backup aus einer .tar.gz Datei wieder her

echo "=========================================="
echo "⚠️ Paperless AI - Restore (Wiederherstellung)"
echo "=========================================="

if [ -z "$1" ]; then
    echo "Fehler: Kein Backup-Pfad angegeben."
    echo "Aufruf: ./restore.sh backups/paperless_ai_backup_DATUM.tar.gz"
    exit 1
fi

BACKUP_FILE="$1"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Fehler: Backup-Datei '$BACKUP_FILE' nicht gefunden!"
    exit 1
fi

echo "ACHTUNG: Dies ueberschreibt deine aktuellen Dokumente, Datenbanken und Skripte endgueltig!"
read -p "Bist du absolut sicher? (j/n) " -n 1 -r
echo ""
if [[ ! $REPLY =~ ^[Jj]$ ]]
then
    echo "Abbruch."
    exit 1
fi

echo "[1] Stoppe Container..."
docker compose down

echo "[2] Entpacke Backup-Archiv..."
tar -xzf "$BACKUP_FILE" -C .

echo "[3] Setze Ausführungsrechte für Skripte neu..."
chmod -R 775 ./scripts 2>/dev/null
find ./scripts -name "*.py" -exec chmod +x {} \; 2>/dev/null
chmod +x ./backup.sh ./restore.sh ./update.sh ./install.sh 2>/dev/null

echo "[4] Starte Container..."
docker compose up -d

echo ""
echo "✅ Wiederherstellung aus $BACKUP_FILE erfolgreich."
