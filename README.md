<div align="center">

# Psychology Session Analyzer

### Event-driven pipeline for turning authorized session recordings into structured, evidence-grounded insights

<p>
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="Python 3.11">
  <img src="https://img.shields.io/badge/Architecture-Microservices-6E4BD8" alt="Microservices">
  <img src="https://img.shields.io/badge/Events-RabbitMQ-FF6600?logo=rabbitmq&logoColor=white" alt="RabbitMQ">
  <img src="https://img.shields.io/badge/API-FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/Containers-Docker-2496ED?logo=docker&logoColor=white" alt="Docker">
</p>

</div>

## Overview

Psychology Session Analyzer is an event-driven Python system that processes an authorized recorded session from upload to structured analysis. It separates the workflow into independently deployable services, uses RabbitMQ for asynchronous handoffs, and persists artifacts and results at each stage.

The pipeline extracts audio from an uploaded video, transcribes it with speaker diarization, generates a structured LLM analysis, and exposes completed results through a read-only FastAPI viewer and a lightweight browser dashboard.

> **Educational project, not a clinical product.** This system is not designed or validated for diagnosis, treatment, or clinical decision-making. It must only be used with synthetic, public, or explicitly authorized recordings that contain no personally identifiable health information.

## What it demonstrates

| System design | AI pipeline | Product surface |
| :--- | :--- | :--- |
| Event-driven microservices with durable queues, retries, containers, logging, and separated data stores. | Speaker diarization, transcript chunking, parallel LLM calls, JSON-constrained analysis, cache-first retrieval, and evidence quotes. | Upload API, read-only analysis API, OpenAPI documentation, and a lightweight dashboard for browsing completed analyses. |

## Pipeline architecture

```mermaid
flowchart LR
    U["Authorized sample recording"] --> UP["Upload service\nFastAPI"]
    UP --> V["MinIO\nvideo object storage"]
    UP --> Q1["new_videos"]
    Q1 --> AE["Audio extractor\nffmpeg"]
    AE --> A["MinIO\naudio objects"]
    AE --> Q2["audio_ready"]
    Q2 --> TS["Transcription service\nAssemblyAI diarization"]
    TS --> T["MinIO\ntranscript JSON"]
    TS --> Q3["transcription_ready"]
    Q3 --> LA["LLM analyzer\nOpenAI"]
    LA <--> R["Redis\nanalysis cache"]
    LA --> DB["PostgreSQL\nanalysis records"]
    LA --> M["MinIO\nanalysis JSON"]
    DB --> VS["Viewer service\nFastAPI + dashboard"]
    VS --> B["Browser or API client"]
    DD["DataDog"] -. container logs .-> UP
    DD -. container logs .-> AE
    DD -. container logs .-> TS
    DD -. container logs .-> LA
    DD -. container logs .-> VS
```

The analyzer also emits an `analysis_ready` event after persistence, leaving a clean integration point for future notifications or downstream reporting.

## Analysis output

The LLM stage returns a constrained JSON document instead of free-form text. Depending on the content of an authorized sample, it can include:

- inferred participant roles and per-utterance topic/emotion labels;
- a concise session summary with evidence quotes;
- positive and negative mood triggers;
- suggested next-session follow-up items and homework assignments mentioned in the conversation;
- selected structured indicators when explicitly supported by the transcript.

Long transcripts are split into bounded chunks. The service analyzes chunks concurrently, merges compatible fields, removes duplicate evidence, and refines the final summary and follow-up list. Redis is checked before a new LLM request and PostgreSQL acts as the durable source of truth.

## Local viewer

The viewer service exposes the existing API and a small dashboard at `http://localhost:8001/`. It lists completed sessions and renders the stored analysis without re-running transcription or LLM inference.

| Endpoint | Purpose |
| :--- | :--- |
| `GET /` | Lightweight local dashboard |
| `GET /health` | Service health check |
| `GET /videos` | List analyzed sessions |
| `GET /videos/{session_id}` | Fetch full structured analysis |
| `GET /videos/{session_id}/summary` | Fetch summary only |
| `GET /docs` | Interactive OpenAPI documentation |

## Technology stack

| Area | Tools |
| :--- | :--- |
| APIs | FastAPI, Uvicorn, Pydantic |
| Orchestration | Docker, Docker Compose |
| Events | RabbitMQ with durable queues and manual acknowledgements |
| Storage | MinIO object storage, PostgreSQL |
| AI services | AssemblyAI transcription with speaker labels, OpenAI structured JSON analysis |
| Performance | Redis cache, transcript chunking, parallel LLM calls |
| Observability | Structured service logging, DataDog Agent |

## Run locally

### Prerequisites

- Docker and Docker Compose
- An [AssemblyAI API key](https://www.assemblyai.com/) for transcription
- An OpenAI API key for the analyzer

### Setup

1. Clone the repository and create your local configuration:

   ```bash
   git clone https://github.com/LironTal01/Psychology_Session_Analyzer.git
   cd Psychology_Session_Analyzer
   cp .env.example .env
   ```

2. Add `OPENAI_API_KEY` and `ASSEMBLYAI_API_KEY` to `.env`. Keep `.env` private.
3. Start the system:

   ```bash
   docker compose up --build
   ```

4. Open the local viewer at `http://localhost:8001/` or inspect the API at `http://localhost:8001/docs`.

To collect container logs with DataDog, add `DD_API_KEY` to `.env` and start the optional observability profile instead:

```bash
docker compose --profile observability up --build
```

### Upload an authorized sample

```bash
curl -X POST http://localhost:8000/upload \
  -F "file=@./authorized-sample.mp4"
```

The upload endpoint returns immediately after storing the video and publishing the first event. Processing continues asynchronously; refresh the viewer after the downstream services complete their work.

For local-only development, Docker Compose supplies the bundled MinIO, RabbitMQ, PostgreSQL, and Redis services. The credentials in `docker-compose.yml` are development defaults and must be replaced before any non-local deployment.

## Project structure

```text
.
├── upload_service/            # FastAPI upload endpoint and new_videos publisher
├── audio_extractor_service/   # ffmpeg audio extraction and audio_ready publisher
├── transcription_service/     # AssemblyAI transcription and speaker diarization
├── llm_analyzer_service/      # Cached, structured LLM analysis and persistence
├── viewer_service/            # Read-only API and browser dashboard
├── common/                    # Shared MinIO, RabbitMQ, logging, and config helpers
├── docker-compose.yml         # Local multi-container environment
└── .env.example               # Safe configuration template
```

## Privacy and responsible use

- Do not upload real therapy recordings, identifiable health information, or data without explicit authorization.
- Treat generated labels, summaries, and follow-up suggestions as fallible model output that requires qualified human review.
- Do not expose this local development setup directly to the internet.
- This repository intentionally contains no recordings, transcripts, or API keys.

## Background

Built as part of the **Advanced Systems Development Using AI** course at Reichman University. The assignment required an event-driven, Dockerized microservices system in Python with RabbitMQ, MinIO, FastAPI, centralized logging, transcription with speaker diarization, LLM analysis, caching, and a results API.
