import subprocess
import json
import logging

logger = logging.getLogger("ContainerManager")

class ContainerManager:
    """Steuert Docker-Container über den Unix-Socket mittels curl."""
    
    def __init__(self, socket_path="/var/run/docker.sock"):
        self.socket_path = socket_path

    def is_running(self, container_name: str) -> bool:
        """Prüft, ob ein Container läuft."""
        try:
            cmd = [
                "curl", "--unix-socket", self.socket_path,
                "-s", f"http://localhost/containers/{container_name}/json"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                data = json.loads(result.stdout)
                return data.get("State", {}).get("Running", False)
        except Exception as e:
            logger.error(f"Fehler bei Status-Check für {container_name}: {e}")
        return False

    def ensure_started(self, container_name: str) -> bool:
        """Startet den Container, falls er nicht läuft."""
        if self.is_running(container_name):
            return True
            
        logger.info(f"🚀 Starte Container: {container_name}...")
        try:
            cmd = [
                "curl", "--unix-socket", self.socket_path,
                "-X", "POST", f"http://localhost/containers/{container_name}/start"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                # Docker API gibt 204 No Content bei Erfolg zurück
                return True
        except Exception as e:
            logger.error(f"Fehler beim Starten von {container_name}: {e}")
        return False

    def stop_container(self, container_name: str) -> bool:
        """Stoppt den Container."""
        if not self.is_running(container_name):
            return True
            
        logger.info(f"💤 Stoppe Container: {container_name}...")
        try:
            cmd = [
                "curl", "--unix-socket", self.socket_path,
                "-X", "POST", f"http://localhost/containers/{container_name}/stop"
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                return True
        except Exception as e:
            logger.error(f"Fehler beim Stoppen von {container_name}: {e}")
        return False
