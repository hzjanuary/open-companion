"""Telegram entity-aware command parsing at the infrastructure boundary."""

import re

from app.domain.conversation import NormalizedCommand

_COMMAND = re.compile(r"^/([A-Za-z][A-Za-z0-9_]{0,31})(?:@([A-Za-z0-9_]{5,32}))?$")


class TelegramCommandParseError(ValueError):
    """A malformed command entity cannot be safely normalized."""


def parse_command(
    text: str | None,
    entities: object,
    assistant_username: str | None,
    maximum_argument_length: int,
) -> NormalizedCommand | None:
    """Recognize only a zero-offset Telegram ``bot_command`` entity.

    Telegram entity offsets and lengths are UTF-16 code units rather than Python
    code points.  This parser intentionally does not infer commands from slash
    text when Telegram did not provide an entity.
    """

    if text is None or not isinstance(entities, list):
        return None
    command_entity = next(
        (
            entity
            for entity in entities
            if isinstance(entity, dict)
            and entity.get("type") == "bot_command"
            and entity.get("offset") == 0
        ),
        None,
    )
    if command_entity is None:
        return None
    length = command_entity.get("length")
    if isinstance(length, bool) or not isinstance(length, int) or length <= 0:
        raise TelegramCommandParseError("bot_command entity length is invalid")
    token = _utf16_slice(text, 0, length)
    if token is None:
        raise TelegramCommandParseError("bot_command entity is outside text")
    match = _COMMAND.fullmatch(token)
    if match is None:
        raise TelegramCommandParseError("bot_command token is invalid")
    name, addressed_username = match.groups()
    if addressed_username is not None:
        if (
            assistant_username is None
            or addressed_username.casefold() != assistant_username.casefold()
        ):
            return None
    arguments = _utf16_slice(text, length, _utf16_length(text) - length)
    if arguments is None:
        raise TelegramCommandParseError("bot_command arguments are invalid")
    arguments = arguments.strip()
    if len(arguments) > maximum_argument_length or any(
        ord(character) < 32 for character in arguments
    ):
        raise TelegramCommandParseError("command arguments are invalid")
    return NormalizedCommand(
        name=name.lower(),
        arguments=arguments,
        addressed_to_assistant=True,
    )


def _utf16_length(value: str) -> int:
    return len(value.encode("utf-16-le")) // 2


def _utf16_slice(value: str, offset: int, length: int) -> str | None:
    if offset < 0 or length < 0:
        return None
    encoded = value.encode("utf-16-le")
    start, end = offset * 2, (offset + length) * 2
    if end > len(encoded):
        return None
    try:
        return encoded[start:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return None
