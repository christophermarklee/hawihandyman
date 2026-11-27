"""Shared OAuth client for Cognito sign-in."""

from authlib.integrations.starlette_client import OAuth

from .config import CognitoSettings


def cognito_oauth_client(settings: CognitoSettings):
    oauth = OAuth()
    return oauth.register(
        name="cognito",
        client_id=settings.client_id,
        client_secret=None,
        server_metadata_url=f"{settings.issuer_url}/.well-known/openid-configuration",
        client_kwargs={
            "scope": "openid email profile",
            "code_challenge_method": "S256",
        },
    )
