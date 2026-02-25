import sys
from pathlib import Path
import yaml
import os

# Add scripts to path
scripts_dir = Path("/volume1/docker/paperless-ngx/scripts")
sys.path.append(str(scripts_dir))

from modules.llm_client import LLMClient

def test_autostart():
    config_path = Path("/usr/src/paperless/scripts/ai_config.yaml")
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
    
    print("Initializing LLMClient...")
    llm = LLMClient(config)
    
    print("Triggering embedding (should start container)...")
    embedding = llm.generate_embedding("Dies ist ein Test für den Resource Saver.")
    
    if embedding:
        print("✅ Success: Embedding generated.")
    else:
        print("❌ Error: Failed to generate embedding.")

if __name__ == "__main__":
    test_autostart()
