# syntax=docker/dockerfile:1

# ─── Étape 1 : compilation Tailwind (vanilla frontend, fallback) ───
# Gardé tant que le frontend vanilla existe. Quand on aura supprimé
# frontend/, cette étape pourra disparaître.
FROM node:20-alpine AS tailwind-build
WORKDIR /build

RUN npm install -g tailwindcss@3 @tailwindcss/cli@3 2>/dev/null \
    || npm install -g tailwindcss@3

COPY frontend/tailwind/input.css ./frontend/tailwind/input.css
COPY frontend/tailwind/config.js ./tailwind.config.js
COPY frontend/index.html ./frontend/index.html
COPY frontend/login.html ./frontend/login.html
COPY frontend/js/ ./frontend/js/

RUN tailwindcss -c tailwind.config.js \
    -i ./frontend/tailwind/input.css \
    -o ./frontend/css/tailwind.css \
    --minify

# ─── Étape 2 : build React (Vite + TypeScript) ─────────────────────
# Build en mode production, output dans /react-build/dist qui sera
# copié dans l'image finale. Tailwind PostCSS est inclus dans ce build
# via les devDependencies — aucun lien avec l'étape ci-dessus.
FROM node:20-alpine AS react-build
WORKDIR /react-build

COPY frontend-react/package.json frontend-react/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY frontend-react/ ./
RUN npm run build

# ─── Étape 3 : runtime Python ──────────────────────────────────────
FROM python:3.11-slim

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

# Bump automatique de la version du service worker à chaque build
# pour que les navigateurs re-téléchargent le shell après un deploy
# (sinon les users restent sur l'ancien app.js indéfiniment).
RUN sed -i "s/scalping-shell-v[0-9]\+/scalping-shell-$(date +%s)/" frontend/sw.js

# CSS Tailwind vanilla (fallback frontend).
COPY --from=tailwind-build /build/frontend/css/tailwind.css ./frontend/css/tailwind.css

# Build React (prend le pas sur vanilla quand l'image detecte dist/).
COPY --from=react-build /react-build/dist ./frontend-react/dist

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
