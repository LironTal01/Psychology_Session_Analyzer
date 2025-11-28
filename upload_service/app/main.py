from fastapi import FastAPI, UploadFile, File
from common.storage_client import StorageClient
import os
import uuid

app = FastAPI(title="upload_service")

storage_client = StorageClient()

MINIO_BUCKET = os.getenv("MINIO_BUCKET", "videos")
storage_client.create_bucket_if_not_exists(MINIO_BUCKET)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/upload")
async def upload_file(file: UploadFile = File(...)):
    # Save the file temporarily in the container's disk
    temp_filename = f"/tmp/{uuid.uuid4()}_{file.filename}"

    with open(temp_filename, "wb") as f:
        f.write(await file.read())

    # Upload to MinIO
    storage_client.upload_file(
        bucket=MINIO_BUCKET,
        file_path=temp_filename,
        object_name=file.filename
    )

    # Delete the local file
    os.remove(temp_filename)

    return {"status": "ok", "filename": file.filename}
