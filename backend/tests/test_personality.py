from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.application.personality import (
    PersonalityOverrides,
    PersonalityValues,
    content_hash,
    default_personality,
    merge_effective,
)


def test_personality_defaults_hash_and_merge_are_deterministic() -> None:
    base = default_personality()
    assert content_hash(base) == content_hash(base)
    effective = merge_effective(
        base,
        PersonalityOverrides(humor_level=0, use_member_names=False),
        profile_id=uuid4(),
        profile_version_id=uuid4(),
        profile_version_number=1,
        configuration_revision_id=uuid4(),
        configuration_revision_number=1,
    )
    assert effective["humor_level"] == 0
    assert effective["use_member_names"] is False
    assert effective["allow_sensitive_teasing"] is False


@pytest.mark.parametrize(
    "values",
    [
        {
            "self_reference": "\x00",
            "humor_level": 0.5,
            "teasing_level": 0.2,
            "emoji_frequency": 0.1,
            "sticker_frequency": 0.1,
        },
        {
            "self_reference": "mình",
            "humor_level": 0.5,
            "teasing_level": 0.8,
            "emoji_frequency": 0.1,
            "sticker_frequency": 0.1,
        },
        {
            "self_reference": "mình",
            "humor_level": 0.5,
            "teasing_level": 0.2,
            "emoji_frequency": 0.1,
            "sticker_frequency": 0.1,
            "use_inside_jokes": True,
        },
    ],
)
def test_personality_rejects_unsafe_values(values: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        PersonalityValues(**values)
