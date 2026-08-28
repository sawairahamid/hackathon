# OrchestrAI — Docker image
# FastAPI + SQLite. Both the main app (8000) and the mock vendor API (8001)
# are started via start.py, so a single container handles everything.

FROM python:3.12-slim

WORKDIR /app

# System deps for fpdf2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libfreetype6 libpng16-16 && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Ensure generated/ and data/ directories exist
RUN mkdir -p generated data

# Default env (override with -e or in render.yaml)
ENV HOST=0.0.0.0 \
    PORT=8000 \
    DATABASE_PATH=data/orchestrai.db \
    SUPPLIER_API_URL=http://127.0.0.1:8001

EXPOSE 8000

# start.py boots the mock API on 8001 then uvicorn on 8000.
CMD ["python", "start.py"]
