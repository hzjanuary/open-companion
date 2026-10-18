"""Closed acceptance boundary fidelity and rejection, with no network I/O."""

import pytest

from tests.fixtures.self_host_http import KEY, MODEL, TOKEN, Boundary


@pytest.mark.parametrize("reply", ["701", "702", 701, 702])
def test_closed_delivery_checks_the_stock_adapter_reply_id(reply: str | int) -> None:
    boundary = Boundary()
    status, result = boundary.dispatch(
        f"/bot{TOKEN}/sendMessage",
        {"chat_id": "72000001", "reply_parameters": {"message_id": reply}},
        None,
    )
    assert status == 200
    assert result["ok"] is True
    assert boundary.snapshot()["counts"] == {"sendMessage": 1, "reply_checked": 1}


@pytest.mark.parametrize("reply", [None, "703", "0701", True])
def test_closed_delivery_rejects_wrong_or_missing_reply_target(reply: object) -> None:
    boundary = Boundary()
    status, result = boundary.dispatch(
        f"/bot{TOKEN}/sendMessage",
        {"chat_id": "72000001", "reply_parameters": {"message_id": reply}},
        None,
    )
    assert status == 400
    assert result["ok"] is False
    assert boundary.snapshot()["counts"] == {"sendMessage": 1, "unexpected": 1}


def test_closed_boundary_never_accepts_unknown_telegram_operation() -> None:
    boundary = Boundary()
    status, _ = boundary.dispatch(f"/bot{TOKEN}/setWebhook", {}, None)
    assert status == 404
    assert boundary.snapshot()["counts"] == {"setWebhook": 1, "unexpected": 1}


def test_closed_provider_requires_exact_auth_model_and_structured_output() -> None:
    boundary = Boundary()
    body = {"model": MODEL, "response_format": {"type": "json_schema"}}
    status, _ = boundary.dispatch("/v1/chat/completions", body, "Bearer wrong")
    assert status == 400
    status, _ = boundary.dispatch("/v1/chat/completions", body, f"Bearer {KEY}")
    assert status == 200
    assert boundary.snapshot()["counts"] == {"unexpected": 1, "generation": 1}
