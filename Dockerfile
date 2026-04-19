# syntax=docker/dockerfile:1

# ─── Étape 1 : compilation Tailwind ────────────────────────────────
# Node n'est présent QUE dans cette étape — pas dans l'image finale.
FROM node:20-alpine AS tailwind-build
WORKDIR /build

# Installer le CLI Tailwind v3 (version stable, la v4 change beaucoup)
RUN npm install -g tailwindcss@3 @tailwindcss/cli@3 2>/dev/null \
    || npm install -g tailwindcss@3

# Copier SEULEMENT ce que Tailwind doit scanner :
#   - les fichiers HTML et JS (pour extraire les classes utilisées)
#   - le fichier input CSS
#   - la config Tailwind
COPY frontend/tailwind/input.css ./frontend/tailwind/input.css
COPY frontend/tailwind/config.js ./tailwind.config.js
COPY frontend/index.html ./frontend/index.html
COPY frontend/login.html ./frontend/login.html
COPY frontend/js/ ./frontend/js/

# Compile + purge → CSS minimal (quelques KB si peu de classes utilisées)
RUN tailwindcss -c tailwind.config.js \
    -i ./frontend/tailwind/input.css \
    -o ./frontend/css/tailwind.css \
    --minify

# ─── Étape 2 : runtime Python ──────────────────────────────────────
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

# Remplacer par le CSS compilé depuis l'étape Tailwind.
# Important : après le COPY . . pour que ce fichier ne soit pas écrasé.
COPY --from=tailwind-build /build/frontend/css/tailwind.css ./frontend/css/tailwind.css

EXPOSE 8000

CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
