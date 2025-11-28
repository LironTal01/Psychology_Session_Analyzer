from fastapi import FastAPI

app = FastAPI(title="upload_service")


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "upload_service"}


