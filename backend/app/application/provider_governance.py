"""Pure SPEC-026 capability, routing, and accounting helpers."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ports.provider_governance import ResolvedProviderRoute
from app.domain.planning import ProviderId
from app.domain.provider_governance import WorkloadClass

ROUTING_SCHEMA_VERSION = "provider-routing-v1"
CAPABILITY_SCHEMA_VERSION = "provider-capability-v1"
ALLOWED_REQUIREMENT_KEYS = frozenset(
    {
        "json_schema",
        "json_object",
        "maximum_output_tokens",
        "embedding_dimension",
        "embedding_version",
        "allowed_data_classes",
        "require_current_health",
        "image_input",
        "speech_to_text",
        "audio_format",
        "maximum_audio_bytes",
        "maximum_audio_duration_seconds",
        "text_to_speech",
        "voice_format",
        "maximum_input_characters",
        "maximum_output_bytes",
    }
)


@dataclass(frozen=True, slots=True)
class CapabilityDecision:
    eligible: bool
    reason: str


def validate_requirements(requirements: dict[str, object]) -> None:
    unknown = set(requirements) - ALLOWED_REQUIREMENT_KEYS
    if unknown:
        raise ValueError("routing requirements contain unknown keys")
    if "maximum_output_tokens" in requirements and (
        type(requirements["maximum_output_tokens"]) is not int
        or int(requirements["maximum_output_tokens"]) <= 0
    ):
        raise ValueError("maximum_output_tokens must be a positive integer")
    if "embedding_dimension" in requirements and (
        type(requirements["embedding_dimension"]) is not int
        or int(requirements["embedding_dimension"]) <= 0
    ):
        raise ValueError("embedding_dimension must be a positive integer")
    if "embedding_version" in requirements and (
        not isinstance(requirements["embedding_version"], str)
        or not 1 <= len(requirements["embedding_version"]) <= 128
    ):
        raise ValueError("embedding_version must be a bounded string")
    for key in (
        "json_schema",
        "json_object",
        "require_current_health",
        "image_input",
        "speech_to_text",
        "text_to_speech",
    ):
        if key in requirements and not isinstance(requirements[key], bool):
            raise ValueError(f"{key} must be boolean")
    for key, maximum in (
        ("maximum_audio_bytes", 10 * 1024 * 1024),
        ("maximum_audio_duration_seconds", 300),
        ("maximum_input_characters", 4096),
        ("maximum_output_bytes", 5 * 1024 * 1024),
    ):
        value = requirements.get(key)
        if key in requirements and (
            type(value) is not int or not 1 <= value <= maximum
        ):
            raise ValueError("audio requirements must have bounded integer limits")
    if "audio_format" in requirements and requirements["audio_format"] not in (
        "audio/ogg",
        "audio/mpeg",
    ):
        raise ValueError("unsupported audio format")
    if "voice_format" in requirements and requirements["voice_format"] != "ogg_opus":
        raise ValueError("unsupported voice format")
    allowed = requirements.get("allowed_data_classes")
    if allowed is not None and (
        not isinstance(allowed, list)
        or not allowed
        or any(value not in {"local", "approved_external"} for value in allowed)
    ):
        raise ValueError("allowed_data_classes must be a nonempty closed list")


def capability_matches(
    route: ResolvedProviderRoute,
    workload: WorkloadClass,
    requirements: dict[str, object],
) -> CapabilityDecision:
    validate_requirements(requirements)
    metadata = route.capability_metadata
    workload_keys = {
        WorkloadClass.CHAT_GENERATION: {
            "json_schema",
            "json_object",
            "maximum_output_tokens",
            "image_input",
        },
        WorkloadClass.EMBEDDING: {"embedding_dimension", "embedding_version"},
        WorkloadClass.TRANSCRIPTION: {
            "speech_to_text",
            "audio_format",
            "maximum_audio_bytes",
            "maximum_audio_duration_seconds",
        },
        WorkloadClass.TEXT_TO_SPEECH: {
            "text_to_speech",
            "voice_format",
            "maximum_input_characters",
            "maximum_output_bytes",
        },
    }[workload]
    if (
        set(requirements)
        - workload_keys
        - {"allowed_data_classes", "require_current_health"}
    ):
        return CapabilityDecision(False, "unsupported_capability")
    if workload == WorkloadClass.CHAT_GENERATION:
        if requirements.get("image_input") is True:
            image_bound = metadata.get("maximum_image_input_tokens")
            if (
                route.adapter_key
                not in {
                    ProviderId.OPENAI,
                    ProviderId.GROQ,
                    ProviderId.OPENROUTER,
                }
                or metadata.get("image_input") is not True
                or type(image_bound) is not int
                or not 1 <= image_bound <= 1_000_000
            ):
                return CapabilityDecision(False, "unsupported_capability")
        for key in ("json_schema", "json_object"):
            required = requirements.get(key)
            if required is True and metadata.get(key) is not True:
                return CapabilityDecision(False, "unsupported_capability")
        maximum = requirements.get("maximum_output_tokens")
        capability_maximum = metadata.get("maximum_output_tokens")
        if maximum is not None and (
            not isinstance(capability_maximum, int)
            or isinstance(capability_maximum, bool)
            or not isinstance(maximum, int)
            or isinstance(maximum, bool)
            or capability_maximum < maximum
        ):
            return CapabilityDecision(False, "unsupported_capability")
    elif workload == WorkloadClass.EMBEDDING:
        dimension = requirements.get("embedding_dimension")
        version = requirements.get("embedding_version")
        if dimension is not None and metadata.get("embedding_dimension") != dimension:
            return CapabilityDecision(False, "unsupported_capability")
        if version is not None and metadata.get("embedding_version") != version:
            return CapabilityDecision(False, "unsupported_capability")
    elif workload == WorkloadClass.TRANSCRIPTION:
        if (
            route.adapter_key != ProviderId.GROQ
            or metadata.get("speech_to_text") is not True
        ):
            return CapabilityDecision(False, "unsupported_capability")
        formats = metadata.get("audio_formats")
        if (
            not isinstance(formats, list)
            or not formats
            or any(item not in ("audio/ogg", "audio/mpeg") for item in formats)
            or (
                "audio_format" in requirements
                and requirements["audio_format"] not in formats
            )
        ):
            return CapabilityDecision(False, "unsupported_capability")
        for key in ("maximum_audio_bytes", "maximum_audio_duration_seconds"):
            available = metadata.get(key)
            required = requirements.get(key, 1)
            if (
                type(available) is not int
                or type(required) is not int
                or available < required
            ):
                return CapabilityDecision(False, "unsupported_capability")
    elif workload == WorkloadClass.TEXT_TO_SPEECH:
        if (
            route.adapter_key != ProviderId.OPENAI
            or metadata.get("text_to_speech") is not True
            or metadata.get("voice_format") != "ogg_opus"
        ):
            return CapabilityDecision(False, "unsupported_capability")
        for key in ("maximum_input_characters", "maximum_output_bytes"):
            available = metadata.get(key)
            required = requirements.get(key, 1)
            if (
                type(available) is not int
                or type(required) is not int
                or available < required
            ):
                return CapabilityDecision(False, "unsupported_capability")
    allowed = requirements.get("allowed_data_classes")
    if isinstance(allowed, list) and route.data_class.value not in allowed:
        return CapabilityDecision(False, "data_ineligible")
    return CapabilityDecision(True, "eligible")


def work_requirements_match(
    published: dict[str, object], requested: dict[str, object], workload: WorkloadClass
) -> bool:
    """Keep published policy exact; allow only additional media restrictions."""
    validate_requirements(published)
    validate_requirements(requested)
    if any(requested.get(key) != value for key, value in published.items()):
        return False
    extra = set(requested) - set(published)
    if workload == WorkloadClass.CHAT_GENERATION:
        return extra <= {"image_input"} and (
            not extra or requested.get("image_input") is True
        )
    if workload == WorkloadClass.TRANSCRIPTION:
        return extra <= {
            "audio_format",
            "maximum_audio_bytes",
            "maximum_audio_duration_seconds",
        }
    if workload == WorkloadClass.TEXT_TO_SPEECH:
        return extra <= {
            "voice_format",
            "maximum_input_characters",
            "maximum_output_bytes",
        }
    return not extra


def conservative_utf8_input_bound(*values: str) -> int:
    """Bound token-like units without storing or returning the input."""

    return sum(len(value.encode("utf-8")) for value in values)
