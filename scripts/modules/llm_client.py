import os
import requests
import time
from typing import Dict, Any, Optional


class LLMClient:
    def __init__(self, config: Dict[str, Any]):
        ollama_cfg = config.get('ollama', {})
        self.host = ollama_cfg.get('url', 'http://localhost:11434') # GPU Host
        self.cpu_host = ollama_cfg.get('cpu_url', self.host) # CPU Host (Fallback auf GPU)
        
        prof_name = ollama_cfg.get('hardware_profile', 'rtx-workstation')
        prof = ollama_cfg.get('profiles', {}).get(prof_name, {})
        
        self.model = prof.get('model', ollama_cfg.get('model', 'qwen2.5vl:7b'))
        self.vision_model = prof.get('vision_model', ollama_cfg.get('vision_model', self.model))
        self.summary_model = prof.get('summary_model', ollama_cfg.get('summary_model', self.model))
        self.embedding_model = prof.get('embedding_model', ollama_cfg.get('embedding_model', "nomic-embed-text"))
        self.timeout = ollama_cfg.get('timeout', 300)
        
        # Container Management
        from .container_manager import ContainerManager
        self.container_mgr = ContainerManager()
        self.cpu_container_name = ollama_cfg.get('cpu_container_name', 'paperless_ollama_cpu')

    def generate(self, prompt: str, system: str = "", context: Optional[list] = None, images: Optional[list] = None, format: Optional[str] = None, model: Optional[str] = None) -> str:
        """Generiert eine Antwort vom LLM via Ollama HTTP API mit Retry-Logik."""
        delays = [5, 10, 15]
        max_attempts = len(delays) + 1
        
        for attempt in range(max_attempts):
            try:
                # Intelligentes Routing: V3.2 No-Swap Policy
                gpu_busy_flag = "/volume1/temp/.gpu_busy"
                
                if images:
                    # Vision-Task: Immer an GPU mit Vision-Modell
                    target_model = self.vision_model
                    target_host = self.host
                else:
                    # Text-Task: Prüfen ob GPU frei ist
                    if not os.path.exists(gpu_busy_flag):
                        # GPU ist frei: Nutze sie für Text, aber mit dem Vision-Modell (Vermeidet Modell-Swap!)
                        target_model = self.vision_model
                        target_host = self.host
                    else:
                        # GPU ist besetzt: Weiche auf CPU aus
                        target_model = self.summary_model
                        target_host = self.cpu_host
                        
                        # Resource Saver: Ensure CPU container is running
                        if target_host == self.cpu_host:
                            self.container_mgr.ensure_started(self.cpu_container_name)

                payload = {
                    "model": target_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.1}
                }
                if system:
                    payload["system"] = system
                if context:
                    payload["context"] = context
                if images:
                    payload["images"] = images
                if format:
                    payload["format"] = format
    
                response = requests.post(
                    f"{target_host}/api/generate",
                    json=payload,
                    timeout=self.timeout
                )
                
                if response.status_code == 200:
                    return response.json().get('response', '').strip()
                elif response.status_code == 500:
                    print(f"Ollama Error: HTTP 500 on attempt {attempt + 1}. ", end="")
                    if attempt < len(delays):
                        wait_time = delays[attempt]
                        print(f"Retrying in {wait_time} seconds...")
                        time.sleep(wait_time)
                    else:
                        print("Max retries reached.")
                        return ""
                else:
                    print(f"Ollama Error: HTTP {response.status_code}")
                    return ""
            except Exception as e:
                print(f"LLM Connection Error on attempt {attempt + 1}: {e}")
                if attempt < len(delays):
                    wait_time = delays[attempt]
                    print(f"Retrying in {wait_time} seconds...")
                    time.sleep(wait_time)
                else:
                    return ""
        return ""

    def generate_embedding(self, text: str) -> list:
        """Erzeugt Embeddings via Ollama HTTP API (Gezielt an CPU gesendet)."""
        # Resource Saver: Ensure CPU container is running
        self.container_mgr.ensure_started(self.cpu_container_name)
        
        try:
            response = requests.post(
                f"{self.cpu_host}/api/embeddings",
                json={"model": self.embedding_model, "prompt": text},
                timeout=180
            )
            if response.status_code == 200:
                return response.json().get('embedding', [])
            return []
        except Exception as e:
            print(f"Embedding Error: {e}")
            return []

    def unload_model(self, model_name: str) -> bool:
        """
        Entfernt ein Modell sofort aus dem VRAM von Ollama (keep_alive=0).
        Hilfreich zur Vermeidung von Out-of-Memory Fehlern bei wenig VRAM.
        """
        try:
            print(f"🧹 Unloading model '{model_name}' from VRAM...")
            response = requests.post(
                f"{self.host}/api/generate",
                json={
                    "model": model_name,
                    "prompt": "",
                    "keep_alive": 0
                },
                timeout=30
            )
            return response.status_code == 200
        except Exception as e:
            print(f"Unload Error for {model_name}: {e}")
            return False
