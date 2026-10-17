from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

ROOT: Path = Path(__file__).resolve().parent.parent
MODELS_PATH: Path = ROOT / "models.json"
UPLOAD_DIR: Path = Path(os.environ.get("UPLOAD_DIR", str(ROOT / "data" / "uploads")))

APIM_BASE_URL: str = os.environ.get(
    "AZURE_LLM_API_ENDPOINT",
    "https://apim-rakathon-q7146n.azure-api.net/openai/v1",
).rstrip("/")

DEFAULT_MODEL: str = os.environ.get("DEFAULT_MODEL", "gpt-6-1-sol-dz-eu")


def api_key() -> str:
    key: str = os.environ.get("AZURE_LLM_API_KEY", "").strip()
    if not key:
        secret: Path = ROOT.parent / ".opencode-secrets" / "apim-api-key"
        if secret.is_file():
            key = secret.read_text(encoding="utf-8").strip()
    if not key:
        raise RuntimeError("AZURE_LLM_API_KEY is not set")
    return key


def load_models() -> list[dict[str, Any]]:
    data: Any = json.loads(MODELS_PATH.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise RuntimeError("models.json must be a list")
    return data


def chat_models(*, multimodal_first: bool = True) -> list[dict[str, Any]]:
    models: list[dict[str, Any]] = [m for m in load_models() if m.get("kind") == "chat"]
    if multimodal_first:
        models.sort(
            key=lambda m: (
                0 if m.get("preferred") else 1,
                0 if m.get("multimodal") else 1,
                0 if m.get("zone") == "eu" else 1,
                str(m.get("label", "")),
            )
        )
    return models
