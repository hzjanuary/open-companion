"""Typed HTTP response contracts."""

from typing import Literal

from pydantic import BaseModel, Field


class ServiceResponse(BaseModel):
    service: str = Field(examples=["January"])
    status: Literal["ok"] = "ok"


class ErrorResponse(BaseModel):
    error_type: Literal["internal_error"]
    message: str
    request_id: str


class DatabaseComponentResponse(BaseModel):
    status: Literal["ok", "unavailable", "disabled"]


class HealthResponse(BaseModel):
    service: str = Field(examples=["January"])
    status: Literal["ok", "degraded"]
    application: DatabaseComponentResponse
    database: DatabaseComponentResponse
    redis: DatabaseComponentResponse


class ReadinessResponse(BaseModel):
    service: str = Field(examples=["January"])
    status: Literal["ok"] = "ok"
    database: DatabaseComponentResponse
    redis: DatabaseComponentResponse


class DependencyUnavailableResponse(BaseModel):
    error_type: Literal["dependency_unavailable"] = "dependency_unavailable"
    message: str = "Database is unavailable"
    request_id: str


class WebhookAcknowledgementResponse(BaseModel):
    status: Literal["accepted"] = "accepted"
    duplicate: bool


class WebhookErrorResponse(BaseModel):
    error_type: Literal["unauthorized", "invalid_request", "ingress_unavailable"]
    message: str
    request_id: str
