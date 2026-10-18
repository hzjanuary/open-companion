"""Strict, provider-independent personality contracts and deterministic merge."""

import hashlib
import json
import math
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

PERSONALITY_SCHEMA_VERSION = "personality-profile-v1"


class PersonalityValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    role: Literal["friendly_group_companion"] = "friendly_group_companion"
    primary_language: Literal["vi", "en", "auto"] = "auto"
    self_reference: str = Field(min_length=1, max_length=32)
    default_length: Literal["short", "medium"] = "short"
    formality: Literal["casual", "neutral"] = "casual"
    humor_level: float = Field(ge=0, le=1)
    teasing_level: float = Field(ge=0, le=0.4)
    emoji_frequency: float = Field(ge=0, le=1)
    sticker_frequency: float = Field(ge=0, le=1)
    use_member_names: bool = True
    use_inside_jokes: bool = False
    ask_follow_up_questions: Literal["never", "sometimes", "often"] = "sometimes"
    allow_sensitive_teasing: bool = False
    stop_teasing_on_request: bool = True
    reveal_private_memory_in_groups: bool = False

    @field_validator("self_reference")
    @classmethod
    def safe_self_reference(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped or any(ord(char) < 32 for char in stripped):
            raise ValueError("self_reference must be visible text")
        return stripped

    @field_validator(
        "humor_level", "teasing_level", "emoji_frequency", "sticker_frequency"
    )
    @classmethod
    def finite_frequency(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("personality frequencies must be finite")
        return value

    @model_validator(mode="after")
    def enforce_mvp_boundaries(self) -> "PersonalityValues":
        if self.use_inside_jokes:
            raise ValueError("inside jokes are disabled in the MVP")
        if self.allow_sensitive_teasing:
            raise ValueError("sensitive teasing is disabled in the MVP")
        if not self.stop_teasing_on_request:
            raise ValueError("stop_teasing_on_request must remain true")
        if self.reveal_private_memory_in_groups:
            raise ValueError("private memory disclosure is disabled in the MVP")
        return self


class PersonalityOverrides(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    default_length: Literal["short", "medium"] | None = None
    formality: Literal["casual", "neutral"] | None = None
    humor_level: float | None = Field(default=None, ge=0, le=1)
    teasing_level: float | None = Field(default=None, ge=0, le=0.4)
    emoji_frequency: float | None = Field(default=None, ge=0, le=1)
    sticker_frequency: float | None = Field(default=None, ge=0, le=1)
    use_member_names: bool | None = None
    ask_follow_up_questions: Literal["never", "sometimes", "often"] | None = None

    @field_validator(
        "humor_level", "teasing_level", "emoji_frequency", "sticker_frequency"
    )
    @classmethod
    def finite_optional_frequency(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("personality frequencies must be finite")
        return value


def default_personality() -> PersonalityValues:
    return PersonalityValues(
        self_reference="mình",
        humor_level=0.55,
        teasing_level=0.2,
        emoji_frequency=0.3,
        sticker_frequency=0.15,
    )


def content_hash(values: PersonalityValues) -> str:
    encoded = json.dumps(
        values.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def merge_effective(
    base: PersonalityValues,
    overrides: PersonalityOverrides,
    *,
    profile_id: UUID,
    profile_version_id: UUID,
    profile_version_number: int,
    configuration_revision_id: UUID,
    configuration_revision_number: int,
) -> dict[str, object]:
    values = base.model_dump(mode="python")
    for key, value in overrides.model_dump(exclude_none=True).items():
        values[key] = value
    effective = PersonalityValues.model_validate(values)
    return {
        "profile_id": profile_id,
        "profile_version_id": profile_version_id,
        "profile_version_number": profile_version_number,
        "personality_schema_version": PERSONALITY_SCHEMA_VERSION,
        "configuration_revision_id": configuration_revision_id,
        "configuration_revision_number": configuration_revision_number,
        **effective.model_dump(mode="json"),
    }
