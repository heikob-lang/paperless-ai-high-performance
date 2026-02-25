# Paperless-AI (V3.4) - The High-End Vision Pipeline

Dieses Repository implementiert eine extrem leistungsfähige, asynchrone KI-Pipeline für [Paperless-ngx](https://github.com/paperless-ngx/paperless-ngx).
Es nutzt modernste Vision-Modelle (`qwen2.5vl`), um Dokumente nicht nur zu lesen, sondern sie zu **verstehen**.

## Core Features (V3.4)

- **Asynchrone Vision-Pipeline**: Trennung von CPU (Bildvorbereitung) und GPU (KI-Analyse) für maximale Performance.
- **Retroactive OCR**: Verarbeite Dokumente, die bereits in Paperless sind, einfach durch Vergabe des Tags `AI-OCR` neu.
- **Resource Saver**: Automatisches Stoppen/Starten des Ollama-CPU Containers bei Inaktivität (um Strom und RAM zu sparen).
- **No-Swap Policy**: Intelligentes Routing zwischen GPU und CPU verhindert VRAM-Abstürze.
- **Pre-Vision Duplicate Check**: Vermeidet teure KI-Läufe durch schnellen Text-Embedding-Vergleich (ChromaDB).
- **Full Metadata Extraction**: Erkennt Titel, Daten, Korrespondenten und Tags direkt aus dem visuellen Innhalt.
- **RAG Integration**: Dokumente werden automatisch vektorisiert und stehen für KI-Chatbots zur Verfügung.

## Systemvoraussetzungen

- **Hardware**: Empfohlen 16GB VRAM (z.B. RTX 4060/5060 Ti oder besser).
- **Software**: Docker & Docker-Compose, funktionierende Paperless-ngx Instanz.

## Installation

1. Repository klonen:

   ```bash
   git clone <dein-repo-url>
   cd paperless-ngx-ai
   ```

2. Konfiguration anpassen:

   ```bash
   cp ai_config.yaml.example ai_config.yaml
   # Bearbeite ai_config.yaml mit deinem API-Token und Modellnamen
   ```

3. Docker-Container starten:

   ```bash
   docker-compose up -d --build
   ```

## Nutzung

### Neue Scans

Wirf PDFs einfach in den `scan_input` Ordner. Der `ai-worker` erkennt sie, bereitet sie vor und schickt sie an die GPU. Die Metadaten werden als JSON-Sidecar an Paperless übergeben.

### Retroactive OCR

Wenn du ein altes Dokument neu verarbeiten willst, gib ihm in der Paperless-Oberfläche einfach den Tag `AI-OCR`. Der Hintergrunddienst erkennt das Dokument, lädt es herunter und jagt es durch die KI-Pipeline.

---
*Entwickelt als High-Performance Erweiterung für Paperless-ngx.*
