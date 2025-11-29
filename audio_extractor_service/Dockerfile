FROM python:3.11-slim

WORKDIR /app

COPY audio_extractor_service/requirements.txt .

RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    rm -rf /var/lib/apt/lists/* && \
    pip install --no-cache-dir -r requirements.txt

COPY common /app/common
COPY audio_extractor_service/app ./app

CMD ["python", "-m", "app.main"]


