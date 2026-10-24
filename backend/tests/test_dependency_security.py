"""Security boundaries exercised across the dependency maintenance upgrade."""

import asyncio
import base64
import hashlib
import hmac
import ssl
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock
from uuid import uuid4

import certifi
import httpx
import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.datastructures import URL
from starlette.requests import Request

from app.core.config import Settings
from app.infrastructure.database.database import Database
from app.infrastructure.database.models import ControlOperatorIdentityModel
from app.interface.http.control_plane import principal_for
from app.interface.http.dependencies import database_session
from app.main import create_app

SECRET = "synthetic-security-regression-key-64-bytes-xxxxxxxxxxxxxxxxxxxxxxxx"


def test_tls_bundle_excludes_compromised_emsign_root() -> None:
    context = ssl.create_default_context(cafile=certifi.where())
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    roots = context.get_ca_certs()
    assert roots
    common_names = {
        value
        for certificate in roots
        for component in certificate["subject"]
        for attribute, value in component
        if attribute == "commonName"
    }
    assert "emSign ECC Root CA - G3" not in common_names


def settings() -> Settings:
    return Settings(
        environment="test",
        control_plane_enabled=True,
        control_plane_jwt_secret=SECRET,
        control_plane_jwt_issuer="synthetic-issuer",
        control_plane_jwt_audience="synthetic-audience",
    )


def claims() -> dict[str, object]:
    return {
        "iss": "synthetic-issuer",
        "aud": "synthetic-audience",
        "sub": "synthetic-operator",
        "exp": datetime.now(UTC) + timedelta(minutes=5),
    }


def raw_token(header: bytes, payload: bytes) -> str:
    """Build synthetic malformed input without relying on encoder validation."""
    segments = [base64.urlsafe_b64encode(x).rstrip(b"=") for x in (header, payload)]
    signing_input = b".".join(segments)
    signature = hmac.new(SECRET.encode(), signing_input, hashlib.sha256).digest()
    return (
        signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
    ).decode()


def authenticate(token: str, session: AsyncMock) -> object:
    app = create_app(settings())
    request = Request({"type": "http", "app": app})
    return asyncio.run(principal_for(request, f"Bearer {token}", session))


@pytest.mark.parametrize("secret", [None, "", "x" * 31])
def test_enabled_control_plane_rejects_missing_or_short_secret(
    secret: str | None,
) -> None:
    with pytest.raises(ValidationError, match="control_plane_jwt_secret"):
        Settings(
            environment="test",
            control_plane_enabled=True,
            control_plane_jwt_secret=secret,
            control_plane_jwt_issuer="synthetic-issuer",
            control_plane_jwt_audience="synthetic-audience",
        )


@pytest.mark.parametrize("algorithm", ["HS384", "HS512", "none"])
def test_control_plane_rejects_algorithms_outside_hs256(algorithm: str) -> None:
    token = jwt.encode(
        claims(), "" if algorithm == "none" else SECRET, algorithm=algorithm
    )
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(token, session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


@pytest.mark.parametrize("claim", ["iss", "aud", "sub", "exp"])
def test_control_plane_requires_authority_and_expiry_claims(claim: str) -> None:
    payload = claims()
    del payload[claim]
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(jwt.encode(payload, SECRET, algorithm="HS256"), session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


@pytest.mark.parametrize(
    "claim,value", [("iss", "other"), ("aud", "other"), ("exp", 1)]
)
def test_control_plane_rejects_wrong_authority_or_expired_claims(
    claim: str, value: object
) -> None:
    payload = {**claims(), claim: value}
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(jwt.encode(payload, SECRET, algorithm="HS256"), session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


@pytest.mark.parametrize("nested_header", [True, False])
def test_deeply_nested_jwt_is_an_authentication_error(nested_header: bool) -> None:
    nested = b"[" * 1500 + b"0" + b"]" * 1500
    header = b'{"alg":"HS256","nested":' + nested + b"}"
    token = raw_token(header if nested_header else b'{"alg":"HS256"}', nested)
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(token, session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


def test_valid_operator_token_retains_identity_and_ignores_tenant_claim() -> None:
    payload = {**claims(), "tenant_id": "untrusted-tenant", "role": "tenant_owner"}
    identity = ControlOperatorIdentityModel(
        issuer="synthetic-issuer", subject="synthetic-operator"
    )
    session = AsyncMock()
    session.scalar.return_value = identity
    principal = authenticate(jwt.encode(payload, SECRET, algorithm="HS256"), session)
    assert principal.identity is identity
    # Tenant authorization is resolved separately from database memberships.
    assert not hasattr(principal, "tenant_id")
    assert not hasattr(principal, "role")


def test_unverified_decode_does_not_disable_later_claim_validation() -> None:
    options = {"verify_signature": False}
    expired = jwt.encode({**claims(), "exp": 1}, SECRET, algorithm="HS256")
    jwt.decode(expired, options=options)
    assert options == {"verify_signature": False}
    options["verify_signature"] = True
    with pytest.raises(jwt.ExpiredSignatureError):
        jwt.decode(
            expired,
            SECRET,
            algorithms=["HS256"],
            issuer="synthetic-issuer",
            audience="synthetic-audience",
            options=options,
        )


def test_empty_oct_jwk_is_rejected() -> None:
    with pytest.raises(jwt.InvalidKeyError):
        key = jwt.PyJWK.from_dict({"kty": "oct", "k": "", "alg": "HS256"})
        jwt.decode(raw_token(b'{"alg":"HS256"}', b"{}"), key, algorithms=["HS256"])


def test_testclient_lifespan_and_malformed_host_control_error(monkeypatch) -> None:
    start, stop = AsyncMock(), AsyncMock()
    monkeypatch.setattr(Database, "start", start)
    monkeypatch.setattr(Database, "stop", stop)
    app = create_app(settings())

    async def session_override():
        yield AsyncMock()

    app.dependency_overrides[database_session] = session_override
    with TestClient(app) as client:
        assert client.get("/live").status_code == 200
        response = client.get(
            "/control/v1/tenants",
            headers={
                "Host": "example.invalid/public?ignored=",
                "X-Request-ID": "security",
            },
        )
        assert response.status_code == 401
        assert response.json() == {
            "error_type": "auth_required",
            "message": "Authentication required",
            "request_id": "security",
        }
        assert response.headers["X-Request-ID"] == "security"
    start.assert_awaited_once()
    stop.assert_awaited_once()


def test_invalid_signature_is_rejected_before_identity_lookup() -> None:
    token = jwt.encode(
        claims(), "other-synthetic-signing-secret-32-bytes", algorithm="HS256"
    )
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(token, session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


def test_noncanonical_signature_is_rejected() -> None:
    token = jwt.encode(claims(), SECRET, algorithm="HS256") + "!!!!"
    session = AsyncMock()
    with pytest.raises(HTTPException) as exc:
        authenticate(token, session)
    assert exc.value.status_code == 401
    session.scalar.assert_not_called()


@pytest.mark.parametrize(
    "path", ["@evil.invalid", "//evil.invalid/path", "/control/v1"]
)
def test_request_path_cannot_replace_url_authority(path: str) -> None:
    url = URL(
        scope={
            "type": "http",
            "scheme": "http",
            "server": ("127.0.0.1", 8000),
            "path": path,
            "query_string": b"",
            "headers": [(b"host", b"example.invalid")],
        }
    )
    assert url.hostname == "example.invalid"
    assert url.path == (path if path.startswith("/") else "/" + path)


@pytest.mark.parametrize(
    "body,content_length,secret,status",
    [
        (b"{}", "1025", "synthetic-webhook-secret", 413),
        (b"x" * 1025, "1", "synthetic-webhook-secret", 413),
        (b"{}", "invalid", "synthetic-webhook-secret", 400),
        (b"{", "1", "synthetic-webhook-secret", 400),
        (b"{}", "2", "synthetic-webhook-secret", 400),
        (b"{", "1", "incorrect-secret", 401),
    ],
)
def test_webhook_preserves_authentication_parsing_and_body_limits(
    body: bytes, content_length: str, secret: str, status: int
) -> None:
    async def scenario() -> None:
        connection_id = uuid4()
        app = create_app(
            Settings(
                environment="test",
                telegram_enabled=True,
                telegram_bot_token="synthetic-token",
                telegram_delivery_mode="webhook",
                telegram_platform_connection_id=connection_id,
                telegram_webhook_secret_token="synthetic-webhook-secret",
                telegram_webhook_public_base_url="https://example.invalid",
                telegram_webhook_body_limit_bytes=1024,
            )
        )
        # All cases must fail before accessing persistence or external I/O.
        app.state.database = None
        transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
        try:
            async with httpx.AsyncClient(
                transport=transport, base_url="http://testserver"
            ) as client:
                response = await client.post(
                    f"/api/v1/platforms/telegram/webhook/{connection_id}",
                    content=body,
                    headers={
                        "Content-Length": content_length,
                        "Content-Type": "application/json",
                        "X-Telegram-Bot-Api-Secret-Token": secret,
                        "X-Request-ID": "security-webhook",
                    },
                )
                assert response.status_code == status
                assert response.headers["X-Request-ID"] == "security-webhook"
                assert response.json()["request_id"] == "security-webhook"
        finally:
            await app.state.telegram.aclose()

    asyncio.run(scenario())


def test_concurrent_http_requests_keep_request_ids_isolated() -> None:
    async def scenario() -> None:
        app = create_app(Settings(environment="test"))
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            responses = await asyncio.gather(
                *(
                    client.get("/live", headers={"X-Request-ID": f"security-{index}"})
                    for index in range(20)
                )
            )
        assert all(response.status_code == 200 for response in responses)
        assert [response.headers["X-Request-ID"] for response in responses] == [
            f"security-{index}" for index in range(20)
        ]

    asyncio.run(scenario())
