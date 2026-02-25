FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Wir nutzen gunicorn für Produktion
CMD ["gunicorn", "--bind", "0.0.0.0:8050", "--workers", "1", "--threads", "4", "app:app"]
