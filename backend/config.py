import os
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

load_dotenv(ROOT / ".env")

with open(ROOT / "config" / "config.yaml", encoding="utf-8") as f:
    CONFIG = yaml.safe_load(f)

# Optional: adsb.lol has announced it may require an API key in the future.
ADSB_API_KEY = os.getenv("ADSB_API_KEY") or None
