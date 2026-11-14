"""Auth0 access-token validation and permission dependencies."""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, Protocol

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer


class SigningKeyClient(Protocol):
    def get_signing_key_from_jwt(self, token: str) -> Any: ...


class Auth0TokenVerifier:
    """Validate RS256 tokens issued for the configured Flowgency API."""

    def __init__(
        self,
        domain: str | None = None,
        audience: str | None = None,
        jwks_client: SigningKeyClient | None = None,
    ) -> None:
        self.domain = (domain or os.getenv("AUTH0_DOMAIN", "")).removeprefix("https://").rstrip("/")
        self.audience = audience or os.getenv("AUTH0_AUDIENCE", "")
        self.issuer = f"https://{self.domain}/" if self.domain else ""
        self._jwks_client = jwks_client or (
            jwt.PyJWKClient(f"{self.issuer}.well-known/jwks.json") if self.configured else None
        )

    @property
    def configured(self) -> bool:
        return bool(self.domain and self.audience)

    def verify(self, token: str) -> dict[str, Any]:
        if not self.configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Auth0 token validation is not configured on the backend",
            )
        try:
            if self._jwks_client is None:
                raise RuntimeError("JWKS client is not configured")
            key = self._jwks_client.get_signing_key_from_jwt(token).key
            claims = jwt.decode(
                token,
                key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.PyJWTError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Unable to validate access token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc
        return claims


bearer = HTTPBearer(auto_error=False)


def require_permission(permission: str) -> Callable[..., dict[str, Any]]:
    async def dependency(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
    ) -> dict[str, Any]:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Bearer access token required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        claims = request.app.state.auth0_verifier.verify(credentials.credentials)
        permissions = claims.get("permissions", [])
        if not isinstance(permissions, list) or permission not in permissions:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission}",
            )
        return claims

    return dependency
