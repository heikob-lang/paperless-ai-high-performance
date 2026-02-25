FROM ghcr.io/paperless-ngx/paperless-ngx:latest

# Switch to root for installation
USER root

# Install system dependencies (Poppler for pdf2image)
RUN apt-get update && apt-get install -y poppler-utils build-essential python3-dev && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

# Switch back to paperless user
USER paperless
