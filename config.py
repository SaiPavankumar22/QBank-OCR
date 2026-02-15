"""
config.py
─────────
Central configuration. All secrets come from environment variables.
Copy .env.example → .env and fill in your values before running.
"""
import os

# Load .env BEFORE reading any env vars (required for NEBIUS_KEY, etc.)
from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI

# ── LLM (Nebius / OpenAI-compatible) ─────────────────────────────────────────
NEBIUS_KEY = os.getenv("NEBIUS_KEY", "your-nebius-key-here")
MODEL       = os.getenv("MODEL", "google/gemma-3-27b-it")

client = OpenAI(
    base_url="https://api.studio.nebius.com/v1/",
    api_key=NEBIUS_KEY,
)

# ── MongoDB ───────────────────────────────────────────────────────────────────
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
DB_NAME   = os.getenv("DB_NAME",   "examdb")

# ── App ───────────────────────────────────────────────────────────────────────
APP_HOST = os.getenv("APP_HOST", "0.0.0.0")
APP_PORT = int(os.getenv("APP_PORT", "8000"))
