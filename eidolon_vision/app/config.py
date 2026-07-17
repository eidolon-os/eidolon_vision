"""Service settings (env + config/default.yaml). No secrets in source."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EIDOLON_VISION_", extra="ignore")

    # Transport
    host: str = "127.0.0.1"
    port: int = 8085

    # Hub
    hub_base_url: str = "http://127.0.0.1:8080"
    hub_public_key: str = ""  # PEM; injected at deploy, never committed

    # Vision (CPU)
    face_model_path: str = "models/face_landmarker.task"

    # VLM (⑥ look) — concrete model is a product/cost choice
    vlm_model: str = "gpt-4o-mini"


def load_settings() -> Settings:
    return Settings()
