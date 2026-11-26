"""Environment-driven configuration for HaleClock."""

import os
from pathlib import Path


def database_path() -> Path:
    return Path(os.environ.get("HALECLOCK_DB", "/var/lib/haleclock/haleclock.db"))


def database_url() -> str:
    return f"sqlite:///{database_path()}"


def secret_key() -> str:
    key = os.environ.get("HALECLOCK_SECRET_KEY")
    if not key:
        raise RuntimeError("HALECLOCK_SECRET_KEY must be set")
    return key


def admin_password() -> str:
    password = os.environ.get("HALECLOCK_ADMIN_PASSWORD")
    if not password:
        raise RuntimeError("HALECLOCK_ADMIN_PASSWORD must be set")
    return password
