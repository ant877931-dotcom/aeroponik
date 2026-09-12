import subprocess
import threading
import re
import sys
import os
import time
import firebase_admin
from firebase_admin import credentials, db

# ------------------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------------------
PORT = 8000
FIREBASE_DB_URL = "https://aeroponic-2712d-default-rtdb.firebaseio.com"
SERVICE_ACCOUNT_KEY_PATH = "serviceAccountKey.json" # Download this from Firebase Console

# ------------------------------------------------------------------------------
# Initialize Firebase Admin SDK
# ------------------------------------------------------------------------------
print("[*] Initializing Firebase Admin...")
if not os.path.exists(SERVICE_ACCOUNT_KEY_PATH):
    print(f"[!] ERROR: {SERVICE_ACCOUNT_KEY_PATH} not found.")
    print("    Please download it from Firebase Console -> Project Settings -> Service Accounts")
    print("    and place it in the same directory as runner.py.")
    sys.exit(1)

cred = credentials.Certificate(SERVICE_ACCOUNT_KEY_PATH)
firebase_admin.initialize_app(cred, {
    'databaseURL': FIREBASE_DB_URL
})

def update_firebase_url(url: str):
    try:
        ref = db.reference('/config/api_url')
        ref.set(url)
        print(f"[+] Successfully pushed URL to Firebase RTDB (/config/api_url): {url}")
    except Exception as e:
        print(f"[-] Failed to push URL to Firebase: {e}")

# ------------------------------------------------------------------------------
# Subprocess Handlers
# ------------------------------------------------------------------------------
def run_fastapi():
    print("[*] Starting FastAPI server...")
    # Adjust module path 'app.main:app' if your folder structure differs.
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", str(PORT)],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    return process

def run_cloudflared_and_monitor():
    print("[*] Starting Cloudflared tunnel...")
    # Cloudflared outputs its logs to stderr, not stdout.
    process = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://localhost:{PORT}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    url_pattern = re.compile(r"(https://[a-zA-Z0-9-]+\.trycloudflare\.com)")
    url_found = False

    while True:
        line = process.stderr.readline()
        if not line:
            break
        
        # Optionally print the cloudflare log line to console for debugging:
        # print(f"[CF] {line.strip()}")

        if not url_found:
            match = url_pattern.search(line)
            if match:
                cf_url = match.group(1)
                print(f"\n[+] Cloudflare Tunnel URL established: {cf_url}\n")
                update_firebase_url(cf_url)
                url_found = True

    return process

def main():
    fastapi_proc = None
    cf_proc = None
    try:
        fastapi_proc = run_fastapi()
        # Give FastAPI a second to bind to the port
        time.sleep(2)
        
        cf_thread = threading.Thread(target=run_cloudflared_and_monitor, daemon=True)
        cf_thread.start()

        # Keep main thread alive
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
    finally:
        if fastapi_proc:
            fastapi_proc.terminate()
        if cf_proc:
            cf_proc.terminate()
        print("[*] Shutdown complete.")

if __name__ == "__main__":
    main()
