# config.py
import os

OUTPUT_HTML = "output/dashboard.html"

# Server settings
SERVER_HOST = os.getenv("JOB_HUNTER_HOST", "127.0.0.1")
SERVER_PORT = int(os.getenv("JOB_HUNTER_PORT", "8765"))
