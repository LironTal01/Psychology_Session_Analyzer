FROM python:3.11-slim

WORKDIR /app

COPY upload_service/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY common /app/common

COPY upload_service/app ./app

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

