import os
from dotenv import load_dotenv

# Load environment variables from .env file if available
load_dotenv()

from app import app
from db import init_db

# Ensure all tables and seed records are ready upon boot
try:
    init_db()
except Exception as e:
    print("Database initialization warning:", e)

# Production entrypoint for Gunicorn / Waitress / WSGI servers
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    host = os.environ.get("HOST", "0.0.0.0")

    print(f"🚀 Starting Medicare Production Server on http://{host}:{port}")

    # Use Waitress for robust multi-threaded production serving on Windows & Cross-platform
    try:
        from waitress import serve
        serve(app, host=host, port=port, threads=6)
    except ImportError:
        app.run(host=host, port=port, debug=False)
