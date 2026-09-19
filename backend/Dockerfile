FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (ffmpeg for faster-whisper audio)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake the Whisper weights into the image. Without this the first voice message
# pays a ~75MB download at request time (and fails entirely while offline).
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('base', device='cpu', compute_type='int8')"

# Real Chromium for the form-filler browser driver (never a simulated browser).
RUN playwright install --with-deps chromium

# Copy application code
COPY ./app ./app
COPY ./alembic ./alembic
COPY ./alembic.ini .

# Expose port
EXPOSE 8000

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]