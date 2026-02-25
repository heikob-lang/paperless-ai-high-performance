#!/usr/bin/env python3
import os
import sys
import yaml
import requests

# Ensure modules structure is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.append(current_dir)

from modules.paperless_client import PaperlessClient
try:
    from modules.chroma_client import ChromaClient
except ImportError:
    # Fallback if run outside standard env, though we expect to run in container
    sys.exit("Error: Could not import ChromaClient. Run this script inside the paperless container.")

# Load Configuration
CONFIG_PATH = os.path.join(current_dir, 'ai_config.yaml')

def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f"Error: Config file not found at {CONFIG_PATH}")
        return None
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def main():
    print("--- ChromaDB Cleanup Script Started ---")
    
    config = load_config()
    if not config:
        sys.exit(1)

    # Force localhost if running in container contexts where this script is executed manually
    # But usually ai_config.yaml has the right URL now.
    
    paperless = PaperlessClient(config)
    chroma = ChromaClient()
    
    collection = chroma.collection
    print(f"Connected to ChromaDB. Collection: {collection.name}")
    
    # Get all embeddings
    # Chroma 'get' without ids returns all? Limit might be applied.
    # We use include=['metadatas'] to get IDs and basic info without heavy embeddings
    print("Fetching all vectors from ChromaDB...")
    try:
        all_docs = collection.get(include=['metadatas'])
        ids = all_docs['ids']
        print(f"Total Vectors in DB: {len(ids)}")
    except Exception as e:
        print(f"Error fetching vectors: {e}")
        sys.exit(1)

    if not ids:
        print("Database is empty. Nothing to clean.")
        return

    deleted_count = 0
    checked_count = 0
    
    print("Checking validity of documents against Paperless API...")
    
    for doc_id_str in ids:
        checked_count += 1
        
        # Paperless IDs are integers, Chroma uses strings. 
        # API check: HEAD or GET /api/documents/{id}/
        
        try:
            doc_id = int(doc_id_str)
        except ValueError:
            print(f"⚠️ Vector ID '{doc_id_str}' is not an integer. Skipping/Deleting?")
            # If we expect only int IDs, maybe we should delete weird ones? 
            # Let's verify existence strictly.
            # If strict: delete. For now: warn.
            continue
            
        exists = False
        try:
            # We use a lightweight check. 
            # PaperlessClient.get_document catches 404 and returns None.
            doc = paperless.get_document(doc_id)
            if doc:
                exists = True
        except Exception as e:
            print(f"Error checking document {doc_id}: {e}")
            continue
            
        if not exists:
            print(f"❌ Stale Vector found: ID {doc_id} (Not found in Paperless). Deleting...")
            try:
                collection.delete(ids=[doc_id_str])
                deleted_count += 1
            except Exception as e:
                print(f"Failed to delete {doc_id}: {e}")
        else:
            # Verbose: print(f"✅ ID {doc_id} exists.")
            # Progress indicator every 100 docs
            if checked_count % 100 == 0:
                print(f"Checked {checked_count}/{len(ids)}...")

    print("-" * 30)
    print("Cleanup Finished.")
    print(f"Total Checked: {checked_count}")
    print(f"Total Deleted: {deleted_count}")
    print(f"Remaining: {len(ids) - deleted_count}")

if __name__ == "__main__":
    main()
