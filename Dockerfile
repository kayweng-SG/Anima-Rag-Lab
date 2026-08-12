# AnimaLink triage API — production-ish image
# Build from repo root (anima-rag-lab/):
#   docker build -t animalink-api .
# Run (mount data + .env; download models on first boot or mount HF cache):
#   docker compose up

FROM python:3.11-slim-bookworm

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY scripts ./scripts
COPY frontend ./frontend
COPY data ./data
COPY evals ./evals

ENV ANIMA_API_HOST=0.0.0.0 \
    ANIMA_API_PORT=8000 \
    HF_HOME=/cache/huggingface \
    TRANSFORMERS_CACHE=/cache/huggingface \
    MERCK_EMBEDDER=sentence_transformers \
    MERCK_EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2

EXPOSE 8000

# Vector store + SQLite live under /app/data (bind-mount in compose for persistence).
CMD ["python", "scripts/07_api_server.py"]
