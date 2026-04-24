# syntax=docker/dockerfile:1

# ─── Étape 1 : build React V2 ──────────────────────────────────────
# La SPA React est la seule UI servie. L'ancien frontend HTML/Tailwind
# a été retiré avec le swap / → /v2 (2026-04-24), et l'étape Tailwind
# compile legacy supprimée en conséquence.
FROM node:20-alpine AS react-builder
WORKDIR /build
COPY frontend-react/package.json frontend-react/package-lock.json ./
RUN npm ci
COPY frontend-react/ ./
RUN npm run build

# ─── Étape 2 : runtime Python ──────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

# Injecter le dist React compilé depuis l'étape react-builder.
# Après COPY . . pour ne pas être écrasé par le projet source.
COPY --from=react-builder /build/dist /app/frontend-react/dist

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
