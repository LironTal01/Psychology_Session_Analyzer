import os
from dataclasses import dataclass


@dataclass(frozen=True)
class RabbitMQConfig:
    """Central RabbitMQ configuration shared by all services."""

    host: str = os.getenv("RABBITMQ_HOST", "rabbitmq")
    port: int = int(os.getenv("RABBITMQ_PORT", "5672"))
    user: str = os.getenv("RABBITMQ_USER", "user")
    password: str = os.getenv("RABBITMQ_PASSWORD", "pass")

    new_videos_queue: str = os.getenv("RABBITMQ_QUEUE", "new_videos")
    audio_ready_queue: str = os.getenv("AUDIO_READY_QUEUE", "audio_ready")
    transcription_ready_queue: str = os.getenv(
        "TRANSCRIPTION_READY_QUEUE", "transcription_ready"
    )
    analysis_ready_queue: str = os.getenv("ANALYSIS_READY_QUEUE", "analysis_ready")


rabbitmq = RabbitMQConfig()


@dataclass(frozen=True)
class DatabaseConfig:
    """PostgreSQL connection parameters for the shared analysis DB."""

    host: str = os.getenv("ANALYSIS_DB_HOST", "postgres")
    port: str = os.getenv("ANALYSIS_DB_PORT", "5432")
    name: str = os.getenv("ANALYSIS_DB_NAME", "sessions_db")
    user: str = os.getenv("ANALYSIS_DB_USER", "admin")
    password: str = os.getenv("ANALYSIS_DB_PASSWORD", "admin123")


database = DatabaseConfig()


@dataclass(frozen=True)
class MinioConfig:
    """MinIO connection configuration shared by all services."""

    endpoint: str = os.getenv("MINIO_ENDPOINT", "minio:9000")
    access_key: str = os.getenv("MINIO_ACCESS_KEY", "admin")
    secret_key: str = os.getenv("MINIO_SECRET_KEY", "password123")
    secure: bool = os.getenv("MINIO_SECURE", "false").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


minio = MinioConfig()


@dataclass(frozen=True)
class OpenAIConfig:
    """OpenAI API configuration for the LLM analyzer."""

    api_key: str = os.getenv("OPENAI_API_KEY", "")
    model: str = os.getenv("OPENAI_MODEL", "gpt-5-nano")


openai = OpenAIConfig()



