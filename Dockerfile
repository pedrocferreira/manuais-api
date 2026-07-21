FROM python:3.12-slim

WORKDIR /app

# Dependências do sistema para PyMuPDF
RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends \
        libmupdf-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app/ app/
COPY scripts/ scripts/

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
