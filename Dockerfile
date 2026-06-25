FROM python:3.11-slim

# Install system dependencies needed for yt-dlp and building wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy dependencies first for caching optimization
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy the rest of the backend files
COPY . .

# Ensure data directories exist for your ML models and SQLite
RUN mkdir -p data/models data/features

EXPOSE 8000

# Start production server using clean uvicorn path
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
