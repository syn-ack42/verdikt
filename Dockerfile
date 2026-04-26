# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build
ARG VITE_BASE=/
ENV VITE_BASE=${VITE_BASE}
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --prefer-offline
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Build Python wheels ─────────────────────────────────────────────
FROM python:3.12-slim AS python-build
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc g++ libsqlcipher-dev libffi-dev libssl-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

# Install CPU-only PyTorch first so sentence-transformers doesn't pull CUDA (saves ~2 GB)
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY backend/ /build/backend/
RUN pip install --no-cache-dir /build/backend

# ── Stage 3: Runtime ─────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# Only the runtime SQLCipher shared library — no headers needed
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsqlcipher1 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python-build /venv /venv
COPY --from=frontend-build /build/dist /app/frontend/dist

WORKDIR /app

ENV PATH="/venv/bin:$PATH" \
    VERDIKT_DATA_DIR=/var/lib/verdikt \
    VERDIKT_FRONTEND_DIR=/app/frontend/dist \
    # HuggingFace model cache lives inside the data volume so it survives restarts
    HF_HOME=/var/lib/verdikt/.cache/huggingface \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

VOLUME ["/var/lib/verdikt"]
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8765/api/docs')"

CMD ["uvicorn", "verdikt.api.app:app", "--host", "0.0.0.0", "--port", "8765"]
