from fastapi import FastAPI

from app.core.config import Settings
from app.main import create_app


def test_application_factory_constructs_and_generates_openapi() -> None:
    app = create_app(Settings(environment="test"))

    assert isinstance(app, FastAPI)
    assert "/ready" in app.openapi()["paths"]
