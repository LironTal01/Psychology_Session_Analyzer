import logging

from fastapi import FastAPI

from .router import router as videos_router


logger = logging.getLogger("viewer_service.main")


def create_app() -> FastAPI:
    """
    Create and configure the FastAPI application for the viewer_service.
    The app exposes:
      - GET /health simple health check
      - GET /videos list all analyzed sessions
      - GET /videos/{session_id} -> full analysis for a session
      - GET /videos/{session_id}/summary -> short summary only
    """
    app = FastAPI(
        title="Psychology Session Viewer Service",
        description=(
            "Read-only API for exploring analyzed therapy sessions. "
            "This service does not upload videos or call LLMs – it only "
            "reads analysis results from PostgreSQL (and optionally Redis)."
        ),
        version="1.0.0",
    )

    # Include the videos router under /videos.
    app.include_router(videos_router)

    @app.get("/health")
    async def health() -> dict:
        """
        Simple health check endpoint used by orchestrators and tests.
        """
        return {"status": "ok"}

    return app


app = create_app()


def main() -> None:
    """
    Entrypoint used when running the module directly.

    In Docker we usually run this service via `uvicorn main:app`,
    but having a main() makes local debugging a bit easier.
    """
    import uvicorn

    uvicorn.run("viewer_service.main:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()



