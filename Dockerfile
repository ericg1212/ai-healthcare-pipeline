FROM python:3.13-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

FROM python:3.13-slim

WORKDIR /app

# Debian zlib1g HIGH (CVE-2026-85091), fixed in 1:1.3.dfsg+really1.3.1-1+deb13u1. Upgrade only that package
# until the base image ships the fix.
RUN apt-get update && apt-get install -y --no-install-recommends --only-upgrade zlib1g \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /usr/local/lib/python3.13/site-packages /usr/local/lib/python3.13/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# pip vendors old msgpack/setuptools copies (Trivy HIGH: GHSA-6v7p-g79w-8964,
# CVE-2025-47273). The runtime never installs packages, so drop pip entirely.
RUN python -m pip uninstall -y pip

COPY . .

EXPOSE 8501

CMD ["streamlit", "run", "streamlit_app/app.py", "--server.port=8501", "--server.address=0.0.0.0"]
