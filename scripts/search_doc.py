import sys
import yaml

sys.path.append("/volume1/docker/paperless-ngx/scripts")
from modules.paperless_client import PaperlessClient

with open('/volume1/docker/paperless-ngx/scripts/ai_config.yaml', 'r') as f:
    config = yaml.safe_load(f)
    config['paperless']['url'] = "http://localhost:8000/api"

client = PaperlessClient(config)
results = client.search_documents("Geburtsurkunde E1")
for doc in results:
    if "Geburtsurkunde E1" in str(doc.get('title')):
        print(f"ID: {doc.get('id')}")
        print(f"Original: {doc.get('original_file_name')}")
        print(f"Archived: {doc.get('archived_file_name')}")
