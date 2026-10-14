"""Personal WWH configuration; shared database settings are read-only fallbacks."""

from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path

from dotenv import dotenv_values

TASK_ROOT = Path(__file__).resolve().parent.parent
PERSON_ROOT = TASK_ROOT.parent
PROJECT_ROOT = TASK_ROOT.parents[2]


def settings_values(
    shared: Mapping[str, str | None],
    personal: Mapping[str, str | None],
    environment: Mapping[str, str],
) -> dict[str, str]:
    """Resolve personal settings; only PostgreSQL can fall back to shared .env."""
    defaults = {
        "DEEPSEEK_API_KEY": "",
        "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
        "DEEPSEEK_MODEL": "deepseek-flash",
        "POSTGRES_HOST": "localhost",
        "POSTGRES_PORT": "15432",
        "POSTGRES_DB": "achievement_analytics",
        "POSTGRES_USER": "analyst",
        "POSTGRES_PASSWORD": "",
        "POSTGRES_SSLMODE": "",
    }
    return {
        name: environment.get(name) or personal.get(name)
        or (shared.get(name) if name.startswith("POSTGRES_") else None) or default
        for name, default in defaults.items()
    }


_values = settings_values(
    dotenv_values(PROJECT_ROOT / ".env"),
    dotenv_values(TASK_ROOT / ".env"),
    os.environ,
)
DEEPSEEK_API_KEY: str = _values["DEEPSEEK_API_KEY"]
DEEPSEEK_BASE_URL: str = _values["DEEPSEEK_BASE_URL"]
DEEPSEEK_MODEL: str = _values["DEEPSEEK_MODEL"]
DB_HOST: str = _values["POSTGRES_HOST"]
DB_PORT: int = int(_values["POSTGRES_PORT"])
DB_NAME: str = _values["POSTGRES_DB"]
DB_USER: str = _values["POSTGRES_USER"]
DB_PASSWORD: str = _values["POSTGRES_PASSWORD"]
DB_SSLMODE: str = _values["POSTGRES_SSLMODE"]
