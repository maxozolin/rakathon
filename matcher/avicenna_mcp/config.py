"""Filesystem locations, overridable by environment variables.

Defaults assume the repository layout (`<repo>/matcher/avicenna_mcp/…`, `<repo>/data/…`).
"""

from __future__ import annotations

import os
from pathlib import Path

PKG_DIR = Path(__file__).resolve().parent
MATCHER_DIR = PKG_DIR.parent
REPO_DIR = MATCHER_DIR.parent


def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else default


def ctgov_db() -> Path:
    return _env_path("AVICENNA_CTGOV_DB", REPO_DIR / "data" / "ctgov" / "ctgov.sqlite")


def ctis_db() -> Path:
    return _env_path("AVICENNA_CTIS_DB", REPO_DIR / "data" / "ctis" / "ctis.sqlite")


def catalog_db() -> Path:
    return _env_path("AVICENNA_CATALOG_DB", REPO_DIR / "data" / "catalog" / "trial_catalog.sqlite")


def packs_dir() -> Path:
    return _env_path("AVICENNA_PACKS_DIR", MATCHER_DIR / "packs")


def skills_dir() -> Path:
    return _env_path("AVICENNA_SKILLS_DIR", MATCHER_DIR / "skills")


def schemas_dir() -> Path:
    return MATCHER_DIR / "schemas"


def prompts_dir() -> Path:
    return REPO_DIR / "prompts"
