import os
import sys
import threading
import time
import webbrowser

# Ensure Medicare directory is in Python path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from app import app
from db import init_db

def open_browser():
    time.sleep(1.0)
    print("\n[+] Opening browser at http://127.0.0.1:5000 ...")
    webbrowser.open("http://127.0.0.1:5000/")

if __name__ == "__main__":
    # Ensure database is initialized
    try:
        init_db()
    except Exception as e:
        print(f"[!] DB Init note: {e}")

    print("=======================================================")
    print(" 🏥 MEDICARE HEALTHCARE PORTAL IS RUNNING!")
    print("=======================================================")
    print(" 🌐 Home Page:         http://127.0.0.1:5000/")
    print(" 🔑 Login Page:        http://127.0.0.1:5000/login")
    print(" 🪪 Medical ID Card:   http://127.0.0.1:5000/card/4")
    print("=======================================================")
    print(" Keep this black window open while using Medicare.")
    print(" Press Ctrl+C in this window to stop the server.")
    print("=======================================================\n")

    if not os.environ.get("WERKZEUG_RUN_MAIN"):
        threading.Thread(target=open_browser, daemon=True).start()

    app.run(host="127.0.0.1", port=5000, debug=True)
