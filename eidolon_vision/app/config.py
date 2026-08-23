"""Service settings (env + config/default.yaml). No secrets in source.

Two kinds of knob live here and they are worth keeping apart mentally:
* *wiring* — which capabilities are on, which implementation fills a role. These
  change what the service is.
* *deployment* — ports, paths, URLs. These change where it runs.
"""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="EIDOLON_VISION_", extra="ignore")

    # -- transport ---------------------------------------------------------
    host: str = "127.0.0.1"
    port: int = 8085

    # -- Hub ---------------------------------------------------------------
    # Empty base_url means "no fact sink" — the demo configuration, where facts
    # go only to the audit log and nothing needs a running Hub.
    hub_base_url: str = "http://127.0.0.1:8080"
    hub_public_key: str = ""  # PEM; injected at deploy, never committed

    # -- wiring ------------------------------------------------------------
    # Turning a capability off is deleting a name from this list. Deleting the
    # capability's package works too; this list just stops mentioning it.
    enabled_capabilities: tuple[str, ...] = ("look_on_demand",)

    # Which side computes the `presence` judgement. The device is cheaper and
    # more private (a rejected frame was never sent); the host is stronger.
    #   device     — the ESP32's own ESP-DL judgement, arrives with the burst
    #   host       — frame differencing here (opencv only, no model asset)
    #   host_face  — MediaPipe face detection here (needs the model asset)
    presence_source: Literal["device", "host", "host_face"] = "device"

    # -- interpreters ------------------------------------------------------
    enable_local_ocr: bool = True   # T1, no egress — the default answer path
    enable_cloud_vlm: bool = False  # T3, egress; still needs per-request consent
    vlm_model: str = "gpt-4o-mini"

    # -- assets & logs -----------------------------------------------------
    face_model_path: str = "models/face_landmarker.task"
    audit_log_path: str = "var/audit.jsonl"


def load_settings() -> Settings:
    return Settings()
