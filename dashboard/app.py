from flask import Flask, render_template, jsonify, Response, request
import docker
import subprocess
import os
import re
import requests

app = Flask(__name__)

# Initialize Docker client using the mounted socket
try:
    client = docker.from_env()
except Exception as e:
    print(f"Error connecting to Docker daemon: {e}")
    client = None

# We can specify the scripts directory that will be mounted into this dashboard container.
SCRIPTS_DIR = "/usr/src/paperless/scripts"

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/api/status")
def get_status():
    if not client:
        return jsonify({"error": "Docker socket not available"}), 500

    containers_to_check = [
        "paperless_ai_worker",
        "paperless-webserver",
        "paperless_chromadb",
        "paperless_open_webui"
    ]
    
    statuses = {}
    for name in containers_to_check:
        try:
            container = client.containers.get(name)
            statuses[name] = {"state": container.status, "status": container.attrs['State']['Status']}
        except docker.errors.NotFound:
            statuses[name] = {"state": "not found", "status": "missing"}
        except Exception as e:
            statuses[name] = {"state": "error", "status": str(e)}

    return jsonify(statuses)

@app.route("/api/logs/ai_worker")
def stream_logs():
    if not client:
        return "Docker not available", 500
        
    def generate():
        try:
            container = client.containers.get("paperless_ai_worker")
            # Stream the latest 100 lines, then follow
            for line in container.logs(stream=True, tail=100, follow=True):
                yield line.decode("utf-8")
        except docker.errors.NotFound:
            yield "Wait... paperless_ai_worker container not found.\n"
        except Exception as e:
            yield f"Error reading logs: {e}\n"

    return Response(generate(), mimetype="text/plain")

@app.route("/api/run_script", methods=["POST"])
def run_script():
    data = request.json
    script_name = data.get("script_name")
    
    allowed_scripts = [
        "process_by_tag.py",
        "maintenance_cleanup_vectors.py",
        "chroma_cleanup.py",
        "ai_backfill.py"
    ]
    
    if script_name not in allowed_scripts:
        return jsonify({"error": "Script not allowed"}), 403

    script_path = os.path.join(SCRIPTS_DIR, script_name)
    
    if not os.path.exists(script_path):
        return jsonify({"error": f"Script {script_name} not found in {SCRIPTS_DIR}"}), 404
        
    # We will trigger the script inside the paperless_ai_worker container rather than locally here
    # Because the worker container has all the python dependencies install, whereas this dashboard is lightweight.
    try:
        if not client:
            return jsonify({"error": "Docker socket not available to trigger script"}), 500
            
        worker_container = client.containers.get("paperless_ai_worker")
        # Run detached in the background
        exec_id = worker_container.client.api.exec_create(
            worker_container.id, 
            cmd=f"python3 /usr/src/paperless/scripts/{script_name}", 
            workdir="/usr/src/paperless",
            user="root"
        )
        worker_container.client.api.exec_start(exec_id, detach=True)
        
        return jsonify({"success": True, "message": f"Started {script_name} in paperless_ai_worker"})
    except docker.errors.NotFound:
        return jsonify({"error": "paperless_ai_worker container not running"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/restart_container", methods=["POST"])
def restart_container():
    data = request.json
    container_name = data.get("container_name")
    
    if not client:
        return jsonify({"error": "Docker socket not available"}), 500
        
    try:
        container = client.containers.get(container_name)
        container.restart()
        return jsonify({"success": True, "message": f"{container_name} restarted"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

import datetime
import threading

def perform_backup_task():
    try:
        # Container stoppen (Hardcoded Liste für Paperless Umgebung)
        containers_to_suspend = [
            "paperless-webserver",
            "paperless_ai_worker",
            "paperless_chromadb",
            "paperless_open_webui"
        ]
        
        # Stoppe auch dynamisch db und broker, falls sie andere Namen haben (suche via labels oder image)
        for c in client.containers.list():
            if "postgres" in c.image.tags[0] or "redis" in c.image.tags[0] or "tika" in c.image.tags[0] or "gotenberg" in c.image.tags[0] or "broker" in c.name or "db" in c.name:
                if c.name not in containers_to_suspend and "dashboard" not in c.name:
                    containers_to_suspend.append(c.name)

        print("Stopping containers for backup...")
        for name in containers_to_suspend:
            try:
                container = client.containers.get(name)
                container.stop(timeout=10)
            except Exception:
                pass

        # Erstelle Backup-Ordner
        backup_dir = "/paperless_root/backups"
        os.makedirs(backup_dir, exist_ok=True)
        date_str = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        backup_file = f"paperless_ai_backup_{date_str}.tar.gz"
        backup_path = os.path.join(backup_dir, backup_file)

        print(f"Creating backup archive {backup_file}...")
        # Tar Befehl ausführen
        items_to_backup = ["docker-compose.yaml", "scripts", "dashboard", "media", "data", "pgdata", "chromadb_data", "scan_input"]
        # Filtere existierende Elemente
        existing_items = [item for item in items_to_backup if os.path.exists(os.path.join("/paperless_root", item))]
        
        subprocess.run(
            ["tar", "-czf", backup_path] + existing_items,
            cwd="/paperless_root",
            check=True
        )
        print("Backup created successfully.")

    except Exception as e:
        print(f"Backup failed: {e}")
    finally:
        # Start containers again
        print("Restarting containers...")
        for name in reversed(containers_to_suspend):
            try:
                container = client.containers.get(name)
                container.start()
            except Exception:
                pass
        print("Backup process completed.")

@app.route("/api/backup", methods=["POST"])
def run_system_backup():
    if not client:
        return jsonify({"error": "Docker socket not available"}), 500
        
    # Asynchron in Background-Thread starten, da der Vorgang Minuten dauern kann
    thread = threading.Thread(target=perform_backup_task)
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "message": "System-Backup wurde im Hintergrund gestartet. Dies kann einige Minuten dauern. Dienste werden vorübergehend pausiert."})

def perform_restore_task(backup_path):
    try:
        containers_to_suspend = [
            "paperless-webserver",
            "paperless_ai_worker",
            "paperless_chromadb",
            "paperless_open_webui"
        ]
        
        # Stoppe dynamisch db und broker
        for c in client.containers.list():
            if "postgres" in c.image.tags[0] or "redis" in c.image.tags[0] or "tika" in c.image.tags[0] or "gotenberg" in c.image.tags[0] or "broker" in c.name or "db" in c.name:
                if c.name not in containers_to_suspend and "dashboard" not in c.name:
                    containers_to_suspend.append(c.name)

        print(f"Stopping containers for restore...")
        for name in containers_to_suspend:
            try:
                container = client.containers.get(name)
                container.stop(timeout=10)
            except Exception:
                pass

        print(f"Extracting backup archive {backup_path}...")
        subprocess.run(
            ["tar", "-xzf", backup_path, "-C", "/paperless_root"],
            check=True
        )
        print("Backup extracted successfully.")

        # Set permissions
        subprocess.run(["chmod", "-R", "775", "/paperless_root/scripts"], check=False)
        subprocess.run(["chmod", "+x", "/paperless_root/backup.sh", "/paperless_root/restore.sh", "/paperless_root/update.sh", "/paperless_root/install.sh"], check=False)

    except Exception as e:
        print(f"Restore failed: {e}")
    finally:
        print("Restarting containers...")
        for name in reversed(containers_to_suspend):
            try:
                container = client.containers.get(name)
                container.start()
            except Exception:
                pass
        print("Restore process completed.")

@app.route("/api/list_backups", methods=["GET"])
def list_backups():
    backup_dir = "/paperless_root/backups"
    backups = []
    if os.path.exists(backup_dir):
        for f in os.listdir(backup_dir):
            if f.endswith(".tar.gz"):
                path = os.path.join(backup_dir, f)
                size_mb = os.path.getsize(path) / (1024 * 1024)
                backups.append({"filename": f, "size_mb": round(size_mb, 2)})
        backups.sort(key=lambda x: x["filename"], reverse=True)
    return jsonify({"success": True, "backups": backups})

@app.route("/api/restore", methods=["POST"])
def run_system_restore():
    if not client:
        return jsonify({"error": "Docker socket not available"}), 500
        
    backup_path = None
    backup_dir = "/paperless_root/backups"
    
    # Handle File Upload
    if 'file' in request.files:
        file = request.files['file']
        if file.filename != '':
            os.makedirs(backup_dir, exist_ok=True)
            backup_path = os.path.join(backup_dir, file.filename)
            file.save(backup_path)
    
    # Handle selected filename
    elif 'filename' in request.form:
        filename = request.form.get('filename')
        backup_path = os.path.join(backup_dir, filename)
        if not os.path.exists(backup_path):
            return jsonify({"error": "Selected backup file does not exist"}), 404

    # Handle custom absolute path
    elif 'custom_path' in request.form and request.form.get('custom_path').strip() != '':
        custom_path = request.form.get('custom_path').strip()
        # Ensure it maps relative to /paperless_root if they provided a relative path, or test if absolute
        if not custom_path.startswith('/'):
            custom_path = os.path.join("/paperless_root", custom_path)
        if not os.path.exists(custom_path):
            return jsonify({"error": f"File not found at path: {custom_path}"}), 404
        backup_path = custom_path

    if not backup_path:
        return jsonify({"error": "No valid backup file or path provided"}), 400

    thread = threading.Thread(target=perform_restore_task, args=(backup_path,))
    thread.daemon = True
    thread.start()
    
    return jsonify({"success": True, "message": "System-Wiederherstellung läuft im Hintergrund. Die Website ist gleich für einen Moment nicht erreichbar."})

@app.route("/api/duplicates")
def get_duplicates():
    # 1. Parse token from mounted ai_config.yaml
    token = None
    try:
        with open("/usr/src/paperless/scripts/ai_config.yaml", "r", encoding="utf-8") as f:
            content = f.read()
            # Finde token: "xxxx" unter paperless:
            match = re.search(r'token:\s*["\']?([A-Za-z0-9]+)["\']?', content)
            if match:
                token = match.group(1)
    except Exception as e:
        return jsonify({"error": f"Could not read config: {e}"}), 500
        
    if not token or token == "DEIN_PAPERLESS_TOKEN_HIER":
        return jsonify({"error": "Paperless Token not configured in ai_config.yaml"}), 400

    # 2. Query Paperless API
    headers = {
        "Authorization": f"Token {token}",
        "Accept": "application/json"
    }
    url = "http://paperless-webserver:8000/api/documents/"
    
    try:
        # Paginieren durch alle Dokumente (vereinfacht: die neuesten 1000)
        response = requests.get(url + "?page_size=1000", headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
        
        duplicates = []
        for doc in data.get("results", []):
            notes = doc.get("notes", [])
            for note in notes:
                note_text = note.get("note", "")
                if "compare.html" in note_text:
                    # Extrahiere Link
                    match = re.search(r'(http[s]?://[^\s]+compare\.html\?left=\d+&right=\d+)', note_text)
                    if not match:
                        match = re.search(r'(/static/compare\.html\?left=\d+&right=\d+)', note_text)
                    
                    if match:
                        link = match.group(1)
                        # Wenn relativer link, dann hostname vom client davor setzen (im Frontend)
                        duplicates.append({
                            "doc_id": doc.get("id"),
                            "title": doc.get("title", f"Dokument #{doc.get('id')}"),
                            "link": link
                        })
                        break # Nur einmal pro Dokument
        
        return jsonify({"success": True, "duplicates": duplicates})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    # Listen on all interfaces so docker can map the port
    app.run(host="0.0.0.0", port=8050, debug=False)
