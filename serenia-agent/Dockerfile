FROM python:3.12-slim-bookworm

# Dépendances système minimales
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        bzip2 \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/*

# restic depuis les binaires officiels (version plus récente que Debian)
ARG RESTIC_VERSION=0.17.3
RUN curl -fsSL -o /tmp/restic.bz2 \
        https://github.com/restic/restic/releases/download/v${RESTIC_VERSION}/restic_${RESTIC_VERSION}_linux_amd64.bz2 \
    && bunzip2 /tmp/restic.bz2 \
    && mv /tmp/restic /usr/local/bin/restic \
    && chmod +x /usr/local/bin/restic \
    && restic version \
    && mkdir -p /etc/serenia /var/log/serenia

WORKDIR /app
COPY app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ .

ENV TZ=Europe/Paris
EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
