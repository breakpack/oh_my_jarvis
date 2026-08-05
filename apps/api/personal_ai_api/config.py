from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/personal_ai"
    redis_url: str = "redis://localhost:6379/0"
    ollama_base_url: str = "http://localhost:11434"
    ollama_local_fast_model: str = "gemma4:e2b"
    ollama_embedding_model: str = "bge-m3:latest"
    # "-1" = keep the model resident in memory indefinitely instead of Ollama's
    # default 5m-idle unload; set e.g. "30m" to trade memory back for latency.
    # (OllamaProvider/OllamaEmbeddingProvider normalize a numeric string like
    # "-1" into a JSON number before sending it — Ollama's duration parser
    # rejects a bare "-1" string, it requires a unit such as "30m".)
    ollama_keep_alive: str = "-1"
    # Cloud model (SPEC §11.3): unset = the "--cloud" / non-local_only chat
    # path falls back to Ollama, since there's nothing to authenticate with.
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: str = "http://localhost:3000"

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
