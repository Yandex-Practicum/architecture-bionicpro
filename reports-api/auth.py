import os
import logging
import jwt
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from jwt.exceptions import (
    InvalidTokenError,
    PyJWKClientConnectionError,
    PyJWKClientError,
)


ISSUER = os.environ["KEYCLOAK_ISSUER"].rstrip("/")
JWKS_URL = os.environ["KEYCLOAK_JWKS_URL"]
AUDIENCE = "reports-api"

bearer = HTTPBearer(auto_error=False)

jwks = PyJWKClient(
    JWKS_URL,
    cache_jwk_set=True,
    lifespan=300,
    timeout=10,
)


def require_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail="Требуется аутентификация",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        signing_key = jwks.get_signing_key_from_jwt(
            credentials.credentials
        )

        claims = jwt.decode(
            credentials.credentials,
            signing_key.key,
            algorithms=["RS256"],
            audience=AUDIENCE,
            issuer=ISSUER,
            options={
                "require": ["exp", "iat", "sub", "iss", "aud"],
            },
        )

        subject = claims["sub"]

        if not isinstance(subject, str) or not subject.strip():
            raise ValueError("Invalid subject")

        return subject

    except PyJWKClientConnectionError:
        raise HTTPException(
            status_code=503,
            detail="Сервис проверки токена временно недоступен",
        ) from None

    except (InvalidTokenError, PyJWKClientError, ValueError) as error:
        logging.warning(
            "Access token rejected: %s; missing claim: %s",
            type(error).__name__,
            getattr(error, "claim", "-"),
        )
        raise HTTPException(
            status_code=401,
            detail="Недействительный или истёкший токен",
            headers={"WWW-Authenticate": "Bearer"},
        ) from None