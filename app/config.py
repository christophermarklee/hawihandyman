"""Environment-driven configuration for HaleClock."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CognitoSettings:
    region: str
    user_pool_id: str
    client_id: str
    domain: str
    public_base_url: str
    providers: tuple[str, ...]

    @property
    def issuer_url(self) -> str:
        return (
            f"https://cognito-idp.{self.region}.amazonaws.com/{self.user_pool_id}"
        )


@dataclass(frozen=True)
class SesSettings:
    region: str
    from_address: str
    reply_to_address: str | None


def public_base_url() -> str:
    return os.environ.get(
        "HALECLOCK_PUBLIC_BASE_URL", "https://www.hawihandyman.com"
    ).rstrip("/")


def ses_settings() -> SesSettings | None:
    region = os.environ.get("HALECLOCK_SES_REGION")
    from_address = os.environ.get("HALECLOCK_SES_FROM_ADDRESS")
    if not region or not from_address:
        return None

    return SesSettings(
        region=region,
        from_address=from_address,
        reply_to_address=os.environ.get("HALECLOCK_SES_REPLY_TO_ADDRESS") or None,
    )


def cognito_settings() -> CognitoSettings | None:
    region = os.environ.get("HALECLOCK_COGNITO_REGION")
    user_pool_id = os.environ.get("HALECLOCK_COGNITO_USER_POOL_ID")
    client_id = os.environ.get("HALECLOCK_COGNITO_CLIENT_ID")
    domain = os.environ.get("HALECLOCK_COGNITO_DOMAIN")
    if not region or not user_pool_id or not client_id or not domain:
        return None

    allowed_providers = {"Google", "Facebook", "SignInWithApple"}
    providers = tuple(
        provider
        for provider in os.environ.get("HALECLOCK_COGNITO_PROVIDERS", "").split(",")
        if provider in allowed_providers
    )
    return CognitoSettings(
        region=region,
        user_pool_id=user_pool_id,
        client_id=client_id,
        domain=domain.rstrip("/"),
        public_base_url=public_base_url(),
        providers=providers,
    )


def database_path() -> Path:
    return Path(os.environ.get("HALECLOCK_DB", "/var/lib/haleclock/haleclock.db"))


def database_url() -> str:
    return f"sqlite:///{database_path()}"


def secret_key() -> str:
    key = os.environ.get("HALECLOCK_SECRET_KEY")
    if not key:
        raise RuntimeError("HALECLOCK_SECRET_KEY must be set")
    return key


def admin_emails() -> frozenset[str]:
    return frozenset(
        email.strip().casefold()
        for email in os.environ.get("HALECLOCK_ADMIN_EMAILS", "").split(",")
        if email.strip()
    )
