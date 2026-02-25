# Wir nutzen das offizielle Paperless-ngx Image als Basis
FROM ghcr.io/paperless-ngx/paperless-ngx:latest

# Installiere zusätzliche System-Tools für Reparatur und OCR
USER root
RUN apt-get update && apt-get install -y \
    ghostscript \
    qpdf \
    python3-pip \
    && apt-get clean

# Installiere die benötigten Python-Bibliotheken für die KI-Anbindung
RUN pip install --no-cache-dir ollama pymupdf requests

# Zurück zum Standard-User
USER paperless
