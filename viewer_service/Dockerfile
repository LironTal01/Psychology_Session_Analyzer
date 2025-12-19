FROM python:3.11

WORKDIR /app

# Install system dependencies required to build psycopg2
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY viewer_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared common package and application code
COPY common /app/common
COPY viewer_service /app/viewer_service

EXPOSE 8000

# Run the FastAPI app with uvicorn
CMD ["uvicorn", "viewer_service.main:app", "--host", "0.0.0.0", "--port", "8000"]



