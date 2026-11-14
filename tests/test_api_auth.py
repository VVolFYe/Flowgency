from __future__ import annotations

import asyncio
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import Depends, FastAPI

from backend.api.app import create_app
from backend.api.auth import Auth0TokenVerifier, require_permission


DOMAIN = "flowgency-test.eu.auth0.com"
AUDIENCE = "https://api.flowgency.test"
PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


class StaticJwksClient:
    def get_signing_key_from_jwt(self, token: str) -> SimpleNamespace:
        return SimpleNamespace(key=PRIVATE_KEY.public_key())


class StubSimulationService:
    def open(self) -> None:
        pass

    def shutdown(self) -> None:
        pass

    def status(self) -> dict[str, object]:
        return {
            "state": "idle",
            "simulation_speed": 4.0,
            "control_mode": "fixed",
            "scenario_id": "single_intersection",
            "simulation_time_s": None,
            "has_snapshot": False,
            "error": None,
        }


def make_token(
    permissions: list[str] | None = None,
    *,
    issuer: str = f"https://{DOMAIN}/",
    audience: str = AUDIENCE,
    expires_delta: timedelta = timedelta(minutes=5),
) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": "auth0|test",
            "iss": issuer,
            "aud": audience,
            "iat": now,
            "exp": now + expires_delta,
            "permissions": permissions or [],
        },
        PRIVATE_KEY,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )


def make_app() -> FastAPI:
    verifier = Auth0TokenVerifier(DOMAIN, AUDIENCE, StaticJwksClient())
    return create_app(service=StubSimulationService(), auth0_verifier=verifier)


def request(app: FastAPI, method: str, path: str, **kwargs: object) -> httpx.Response:
    async def send() -> httpx.Response:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as api:
            return await api.request(method, path, **kwargs)

    return asyncio.run(send())


class Auth0ApiSecurityTests(unittest.TestCase):
    def test_every_control_endpoint_requires_token(self) -> None:
        api = make_app()
        for command in ("start", "pause", "resume", "reset", "stop", "speed"):
            with self.subTest(command=command):
                response = request(api, "POST", f"/api/simulation/{command}")
                self.assertEqual(response.status_code, 401)

    def test_invalid_token_is_unauthorized(self) -> None:
        response = request(
            make_app(),
            "POST",
            "/api/simulation/start",
            headers={"Authorization": "Bearer invalid"},
        )
        self.assertEqual(response.status_code, 401)

    def test_valid_token_without_control_permission_is_forbidden(self) -> None:
        response = request(
            make_app(),
            "POST",
            "/api/simulation/start",
            headers={"Authorization": f"Bearer {make_token(['simulation:read'])}"},
        )
        self.assertEqual(response.status_code, 403)

    def test_operator_token_passes_authorization(self) -> None:
        api = FastAPI()
        api.state.auth0_verifier = Auth0TokenVerifier(
            DOMAIN, AUDIENCE, StaticJwksClient()
        )

        @api.post(
            "/control",
            dependencies=[Depends(require_permission("simulation:control"))],
        )
        async def control() -> dict[str, bool]:
            return {"authorized": True}

        response = request(
            api,
            "POST",
            "/control",
            headers={"Authorization": f"Bearer {make_token(['simulation:control'])}"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"authorized": True})

    def test_wrong_issuer_is_unauthorized(self) -> None:
        response = request(
            make_app(),
            "POST",
            "/api/simulation/start",
            headers={
                "Authorization": f"Bearer {make_token(['simulation:control'], issuer='https://wrong.example/')}"
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_wrong_audience_is_unauthorized(self) -> None:
        response = request(
            make_app(),
            "POST",
            "/api/simulation/start",
            headers={
                "Authorization": f"Bearer {make_token(['simulation:control'], audience='wrong-audience')}"
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_expired_token_is_unauthorized(self) -> None:
        response = request(
            make_app(),
            "POST",
            "/api/simulation/start",
            headers={
                "Authorization": f"Bearer {make_token(['simulation:control'], expires_delta=timedelta(minutes=-1))}"
            },
        )
        self.assertEqual(response.status_code, 401)

    def test_public_status_remains_available(self) -> None:
        response = request(make_app(), "GET", "/api/simulation/status")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["state"], "idle")


if __name__ == "__main__":
    unittest.main()
