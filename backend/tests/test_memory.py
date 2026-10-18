import pytest

from app.application.memory import MemoryValidationError, normalize_explicit_memory
from app.domain.persistence import MemoryScope


def test_explicit_memory_normalizes_whitespace_without_inference() -> None:
    memory = normalize_explicit_memory(
        "  a\u00a0 fact\n", MemoryScope.GROUP_CONVERSATION
    )
    assert memory.content == "a fact"
    assert memory.confidence == 1.0


@pytest.mark.parametrize("content", ["", "\x00", "x" * 501])
def test_explicit_memory_rejects_invalid_content(content: str) -> None:
    with pytest.raises(MemoryValidationError):
        normalize_explicit_memory(content, MemoryScope.PRIVATE_CONVERSATION)
