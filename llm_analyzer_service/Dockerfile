FROM python:3.11-slim

WORKDIR /app

# Install Python dependencies for this microservice
COPY llm_analyzer_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy shared code and this microservice as a proper package
COPY common /app/common
COPY llm_analyzer_service /app/llm_analyzer_service

# Run the llm_analyzer_service package entrypoint
CMD ["python", "-m", "llm_analyzer_service.main"]



