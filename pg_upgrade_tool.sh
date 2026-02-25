#!/bin/bash
# Paperless AI Workflow - PostgreSQL Upgrade Tool (V3.5)
# Ermöglicht sichere Major-Version Upgrades von PostgreSQL in Docker

set -e

DB_CONTAINER="paperless-ngx-db-1"
COMPOSE_FILE="docker-compose.yaml"
PGDATA_DIR="./pgdata"
BACKUP_DIR="./backups/db_upgrades"
DATE=$(date +"%Y-%m-%d_%H-%M-%S")
DUMP_FILE="$BACKUP_DIR/full_dump_$DATE.sql"

echo "=========================================="
echo "🐘 PostgreSQL Upgrade Tool V3.5"
echo "=========================================="

mkdir -p "$BACKUP_DIR"

# 1. Check if DB container is running
if ! docker ps | grep -q "$DB_CONTAINER"; then
    echo "❌ Fehler: Der Container $DB_CONTAINER läuft nicht."
    echo "Stelle sicher, dass die alte DB-Version aktiv ist, um den Dump zu erstellen."
    exit 1
fi

echo "[1] Erstelle vollständigen SQL-Dump (pg_dumpall)..."
# Wir nutzen docker exec um den Dump direkt aus dem laufenden Container zu ziehen
docker exec "$DB_CONTAINER" pg_dumpall -U paperless > "$DUMP_FILE"
echo "✅ Dump erstellt: $DUMP_FILE ($(du -h "$DUMP_FILE" | cut -f1))"

echo "[2] Stoppe die gesamte Infrastruktur..."
docker-compose stop

echo "[3] Sichere aktuelles pgdata Verzeichnis..."
MV_TARGET="pgdata_backup_pre_upgrade_$DATE"
mv "$PGDATA_DIR" "$PGDATA_DIR.archive/$MV_TARGET" 2>/dev/null || mv "$PGDATA_DIR" "$BACKUP_DIR/$MV_TARGET"
echo "✅ $PGDATA_DIR wurde nach $BACKUP_DIR/$MV_TARGET verschoben."

echo "----------------------------------------------------"
echo "⚠️  AKTION ERFORDERLICH ⚠️"
echo "Bitte ändere jetzt in der $COMPOSE_FILE die Postgres-Version."
echo "Beispiel: postgres:16 -> postgres:17"
echo "----------------------------------------------------"
read -p "Drücke ENTER, wenn du die Version in der Datei angepasst hast..."

echo "[4] Starte neuen (leeren) Datenbank-Container..."
docker-compose up -d db

echo "Warte auf DB-Initialisierung (10 Sek)..."
sleep 10

echo "[5] Importiere SQL-Dump in die neue Version..."
cat "$DUMP_FILE" | docker exec -i "$DB_CONTAINER" psql -U paperless -d paperless

echo "[6] Starte restliche Container..."
docker-compose up -d

echo "=========================================="
echo "✅ Upgrade abgeschlossen!"
echo "Bitte prüfe die Paperless-Oberfläche auf Funktion."
echo "Dein altes Datenverzeichnis liegt in: $BACKUP_DIR/$MV_TARGET"
echo "=========================================="
