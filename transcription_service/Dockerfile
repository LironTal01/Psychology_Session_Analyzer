FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies
COPY transcription_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared code and this microservice as a proper package
COPY common /app/common
COPY transcription_service /app/transcription_service

# Run the transcription_service package entrypoint
CMD ["python", "-m", "transcription_service.main"]



