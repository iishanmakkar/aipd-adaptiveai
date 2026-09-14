FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# torch defaults to CUDA wheels: ~5.5 GB of nvidia-* packages that this CPU-only
# service never uses. Install the CPU build from the PyTorch CPU index first so
# pip treats torch as already satisfied and skips the GPU wheels entirely
# (image drops from ~9 GB to ~1 GB).
RUN pip install --no-cache-dir torch==2.3.1 --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
