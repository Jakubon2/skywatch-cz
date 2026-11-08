# Backend image. Build context is backend/ (see docker-compose.yml).
# Layout mirrors the repo, because config.ROOT is the parent of backend/:
#   /app/backend  code (this image)
#   /app/config   mounted read-only from the repo
#   /app/data     volume: SQLite + OurAirports CSVs
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1
WORKDIR /app/backend

COPY requirements.txt .
# tzdata: zoneinfo fallback (explain.py uses Europe/Prague); slim images may lack system tz data.
RUN pip install -r requirements.txt tzdata

# Explicit copies keep .venv, tests and caches out of the image.
COPY *.py ./
COPY detectors/ detectors/

RUN useradd --uid 1000 --create-home app && mkdir -p /app/data && chown app /app/data
USER app

EXPOSE 8000
# Exactly one worker: the adsb.lol poller runs inside the app process, more workers = more pollers.
CMD ["uvicorn", "api:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
