"""Application-level content-free telemetry helpers."""

from app.application.ports.telemetry import MetricsRecorder


def record_provider_usage(
    recorder: MetricsRecorder,
    *,
    provider: str,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
    total_tokens: int | None,
    pricing: dict[str, dict[str, int]],
) -> None:
    """Record reported usage only; missing values never fabricate a cost."""

    values = (input_tokens, output_tokens, total_tokens)
    if any(
        value is not None and (not isinstance(value, int) or value < 0)
        for value in values
    ):
        recorder.increment(
            "january_model_usage_reports_total", provider=provider, outcome="invalid"
        )
        return
    if input_tokens is None and output_tokens is None and total_tokens is None:
        recorder.increment(
            "january_model_usage_reports_total", provider=provider, outcome="missing"
        )
        recorder.increment(
            "january_model_cost_estimate_total",
            provider=provider,
            outcome="unavailable",
        )
        return
    outcome = (
        "complete"
        if input_tokens is not None and output_tokens is not None
        else "partial"
    )
    recorder.increment(
        "january_model_usage_reports_total", provider=provider, outcome=outcome
    )
    for token_type, amount in (
        ("input", input_tokens),
        ("output", output_tokens),
        ("total", total_tokens),
    ):
        if amount is not None:
            recorder.increment(
                "january_model_tokens_total",
                amount,
                provider=provider,
                token_type=token_type,
            )
    rates = pricing.get(f"{provider}:{model}")
    if rates is None or input_tokens is None or output_tokens is None:
        recorder.increment(
            "january_model_cost_estimate_total",
            provider=provider,
            outcome="unavailable",
        )
        return
    micro_usd = (
        input_tokens * rates["input_microusd_per_million"]
        + output_tokens * rates["output_microusd_per_million"]
    ) / 1_000_000
    recorder.increment(
        "january_model_estimated_cost_usd_total",
        micro_usd / 1_000_000,
        provider=provider,
    )
    recorder.increment(
        "january_model_cost_estimate_total", provider=provider, outcome="estimated"
    )
