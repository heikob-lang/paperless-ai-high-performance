#!/usr/bin/env python3
import os
import sys
import yaml
import requests
import time

# Ensure modules structure is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from modules.chroma_client import ChromaClient

# Load Configuration
CONFIG_PATH = os.path.join(current_dir, 'ai_config.yaml')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}")
        sys.exit(1)
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def get_all_paperless_documents(config):
    """Fetches all documents from Paperless API with pagination."""
    api_url = config['paperless']['url'].rstrip('/')
    token = config['paperless']['token']
    headers = {"Authorization": f"Token {token}"}
    
    documents = []
    next_url = f"{api_url}/documents/?page_size=100"
    
    print(f"Fetching documents from {api_url}...")
    
    while next_url:
        try:
            response = requests.get(next_url, headers=headers)
            response.raise_for_status()
            data = response.json()
            
            results = data.get('results', [])
            documents.extend(results)
            
            print(f"Fetched {len(results)} documents (Total: {len(documents)})")
            
            next_url = data.get('next')
        except Exception as e:
            print(f"Error fetching documents: {e}")
            break
            
    return documents

def main():
    print("--- Starting ChromaDB Re-Indexing ---")
    config = load_config()
    chroma = ChromaClient()
    
    # 1. Fetch all documents from Paperless
    docs = get_all_paperless_documents(config)
    print(f"Total documents in Paperless: {len(docs)}")
    
    # 2. Add to ChromaDB
    success_count: int = 0
    error_count: int = 0
    
    for doc in docs:
        doc_id = doc.get('id')
        title = doc.get('title', 'Unknown')
        content = doc.get('content', '')
        correspondent = doc.get('correspondent')
        created = doc.get('created')
        
        print(f"Indexing Document {doc_id}: {title}...")
        
        meta = {
            "title": title,
            "correspondent": str(correspondent) if correspondent else '',
            "created": created if created else ''
        }
        
        try:
            if chroma.add_document(doc_id, content, meta):
                success_count = success_count + 1 # type: ignore
            else:
                print(f"Failed to index Document {doc_id} (empty content?)")
                error_count = error_count + 1
        except Exception as e:
            print(f"Error indexing Document {doc_id}: {e}")
            error_count = error_count + 1
            
    print("-" * 30)
    print(f"Re-Indexing Complete.")
    print(f"Successfully indexed: {success_count}")
    print(f"Failed/Skipped: {error_count}")
    print(f"Total in ChromaDB: {chroma.count()}")

if __name__ == "__main__":
    main()
