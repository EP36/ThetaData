FROM python:3.11-slim

WORKDIR /app

# Install system deps needed by some Python packages (psycopg binary, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY trauto/ trauto/
COPY scripts/ scripts/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

CMD ["python", "-m", "src.worker"]
