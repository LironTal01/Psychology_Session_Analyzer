import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .router import router as videos_router


logger = logging.getLogger("viewer_service.main")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Create the read-only API and lightweight local viewer."""
    app = FastAPI(
        title="Psychology Session Viewer Service",
        description=(
            "Read-only API for exploring analyzed sessions. "
            "The service reads persisted analysis results; it does not upload "
            "videos or call an LLM."
        ),
        version="1.1.0",
    )

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    app.include_router(videos_router)

    @app.get("/", include_in_schema=False)
    async def dashboard() -> FileResponse:
        """Serve a small local dashboard over the existing viewer API."""
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/health")
    async def health() -> dict:
        """Simple health check endpoint used by orchestrators and tests."""
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    """Entrypoint used when running the module directly."""
    import uvicorn

    uvicorn.run("viewer_service.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
