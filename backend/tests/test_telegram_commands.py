from uuid import uuid4

import pytest

from app.application.commands import CommandOperation, command_response, parse_command
from app.core.config import Settings
from app.domain.feedback import FeedbackValue
from app.infrastructure.database.models import ParticipantModel
from app.infrastructure.telegram.commands import (
    TelegramCommandParseError,
)
from app.infrastructure.telegram.commands import (
    parse_command as parse_telegram_command,
)
from app.runtime.telegram_command_worker import (
    _authorization_retry_delay,
    _configuration_change,
)


@pytest.mark.parametrize("language", ["en", "vi", "auto"])
def test_product_owned_checkin_copy_uses_canonical_name(language: str) -> None:
    text = command_response("schedule_checkin", language=language)
    assert text.startswith("January ")
    phrase = "How are you doing today?" if language == "en" else "Hom nay"
    assert phrase in text
    assert command_response("schedule_checkin", language=language, detail="extra") == (
        f"{text} extra"
    )


def test_entity_command_normalizes_and_trims_arguments() -> None:
    command = parse_telegram_command(
        "/MoDe@JanuaryBot mention_only  ",
        [{"type": "bot_command", "offset": 0, "length": 16}],
        "JanuaryBot",
        160,
    )
    assert command is not None
    assert (command.name, command.arguments) == ("mode", "mention_only")


def test_other_bot_and_slash_prose_are_not_commands() -> None:
    assert (
        parse_telegram_command(
            "/status@OtherBot",
            [{"type": "bot_command", "offset": 0, "length": 16}],
            "JanuaryBot",
            160,
        )
        is None
    )
    assert parse_telegram_command("/status", [], "JanuaryBot", 160) is None


def test_utf16_entity_offsets_are_checked() -> None:
    command = parse_telegram_command(
        "/status hello 😀",
        [{"type": "bot_command", "offset": 0, "length": 7}],
        "JanuaryBot",
        160,
    )
    assert command is not None and command.name == "status"
    try:
        parse_telegram_command(
            "/status",
            [{"type": "bot_command", "offset": 0, "length": 99}],
            "JanuaryBot",
            160,
        )
    except TelegramCommandParseError:
        pass
    else:
        raise AssertionError("out-of-range entity must be rejected")


def test_command_grammar_is_bounded() -> None:
    assert (
        parse_command("mode", "mention_and_name").operation
        == CommandOperation.CONFIGURATION
    )
    assert parse_command("mode", "paused").operation == CommandOperation.USAGE
    assert (
        parse_command("personality", "use lively@2").operation
        == CommandOperation.CONFIGURATION
    )
    assert parse_command("personality", "use {bad}").operation == CommandOperation.USAGE
    assert parse_command("mentions", "off").operation == CommandOperation.PREFERENCE


@pytest.mark.parametrize(
    ("name", "arguments", "operation", "action", "value"),
    [
        ("start", "", CommandOperation.READ, "status", None),
        ("help", "", CommandOperation.READ, "status", None),
        ("status", "", CommandOperation.READ, "status", None),
        ("regenerate", "", CommandOperation.REGENERATION, "regenerate", None),
        (
            "feedback",
            "helpful",
            CommandOperation.FEEDBACK,
            "set",
            FeedbackValue.HELPFUL,
        ),
        (
            "feedback",
            "unhelpful",
            CommandOperation.FEEDBACK,
            "set",
            FeedbackValue.UNHELPFUL,
        ),
        ("mode", "status", CommandOperation.READ, "status", None),
        (
            "mode",
            "mention_only",
            CommandOperation.CONFIGURATION,
            "mode",
            "mention_only",
        ),
        (
            "mode",
            "mention_and_name",
            CommandOperation.CONFIGURATION,
            "mode",
            "mention_and_name",
        ),
        (
            "mode",
            "ambient_selective",
            CommandOperation.CONFIGURATION,
            "mode",
            "ambient_selective",
        ),
        ("frequency", "", CommandOperation.READ, "status", None),
        ("frequency", "status", CommandOperation.READ, "status", None),
        (
            "frequency",
            "low",
            CommandOperation.CONFIGURATION,
            "frequency",
            "low",
        ),
        (
            "frequency",
            "normal",
            CommandOperation.CONFIGURATION,
            "frequency",
            "normal",
        ),
        (
            "frequency",
            "high",
            CommandOperation.CONFIGURATION,
            "frequency",
            "high",
        ),
        ("quiet", "", CommandOperation.CONFIGURATION, "quiet", None),
        ("resume", "", CommandOperation.CONFIGURATION, "resume", None),
        ("personality", "list", CommandOperation.READ, "list", None),
        ("personality", "use lively", CommandOperation.CONFIGURATION, "use", "lively"),
        (
            "personality",
            "use lively@12",
            CommandOperation.CONFIGURATION,
            "use",
            "lively@12",
        ),
        ("stickers", "on", CommandOperation.CONFIGURATION, "set", True),
        ("stickers", "off", CommandOperation.CONFIGURATION, "set", False),
        ("mentions", "on", CommandOperation.PREFERENCE, "set", True),
        ("teasing", "off", CommandOperation.PREFERENCE, "set", False),
        ("safety", "", CommandOperation.READ, "status", None),
        ("safety", "status", CommandOperation.READ, "status", None),
        (
            "safety",
            "strict",
            CommandOperation.CONFIGURATION,
            "set_safety_level",
            "strict",
        ),
        (
            "safety",
            "standard",
            CommandOperation.CONFIGURATION,
            "set_safety_level",
            "standard",
        ),
        (
            "safety",
            "relaxed",
            CommandOperation.CONFIGURATION,
            "set_safety_level",
            "relaxed",
        ),
        (
            "safety",
            "teasing 3",
            CommandOperation.CONFIGURATION,
            "set_teasing_cap",
            "3",
        ),
        ("protect", "", CommandOperation.CONFIGURATION, "protect", True),
        ("unprotect", "", CommandOperation.CONFIGURATION, "unprotect", False),
        (
            "export_my_data",
            "",
            CommandOperation.GOVERNANCE,
            "export_subject",
            None,
        ),
        (
            "export_group_data",
            "",
            CommandOperation.GOVERNANCE,
            "export_group",
            None,
        ),
        ("data_summary", "", CommandOperation.GOVERNANCE, "summary", None),
    ],
)
def test_every_accepted_command_form_has_a_typed_result(
    name: str,
    arguments: str,
    operation: CommandOperation,
    action: str,
    value: str | bool | None,
) -> None:
    result = parse_command(name, arguments)
    assert (result.operation, result.action, result.value) == (operation, action, value)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("start", "now"),
        ("quiet", "please"),
        ("mode", "paused"),
        ("frequency", "fast"),
        ("personality", "use arbitrary prompt text"),
        ("personality", "use {json}"),
        ("stickers", "maybe"),
        ("mentions", "other-user off"),
        ("teasing", "off extra"),
        ("safety", "strict extra"),
        ("safety", "teasing"),
        ("safety", "teasing 0"),
        ("safety", "teasing 10"),
        ("safety", "teasing two"),
        ("protect", "someone"),
        ("unprotect", "target"),
        ("export_my_data", "now"),
        ("export_group_data", "please"),
        ("data_summary", "extra"),
        ("feedback", ""),
        ("feedback", "maybe"),
        ("feedback", "5"),
        ("feedback", "useful because it was clear"),
        ("feedback", "helpful extra text"),
    ],
)
def test_malformed_command_forms_are_usage_errors(name: str, arguments: str) -> None:
    assert parse_command(name, arguments).operation == CommandOperation.USAGE


def test_authorization_retry_delay_is_exponential_and_bounded() -> None:
    settings = Settings(
        _env_file=None,
        command_retry_min_delay_seconds=2,
        command_retry_max_delay_seconds=5,
    )
    assert _authorization_retry_delay(settings, 1) == 2
    assert _authorization_retry_delay(settings, 2) == 4
    assert _authorization_retry_delay(settings, 3) == 5


@pytest.mark.parametrize(
    ("name", "arguments", "action"),
    [
        ("memory", "", "summary"),
        ("memory", "list", "list"),
        ("memory", "remember a fact", "remember"),
        ("memory", "context add preferred_name Mai", "context_create"),
        ("memory", "update Abc12345 2 corrected fact", "update"),
        ("memory", "delete Abc12345 2", "delete"),
        ("memory", "clear_mine confirm", "clear_mine"),
        ("memory", "recall status", "recall_status"),
        ("memory", "recall off", "recall_off"),
        ("memory", "recall on", "recall_on"),
        ("memory", "reset_group confirm", "reset_group"),
        ("forget", "Abc12345", "forget"),
        ("forget_me", "", "warning"),
        ("forget_me", "confirm", "confirm"),
    ],
)
def test_memory_command_grammar_is_exact(
    name: str, arguments: str, action: str
) -> None:
    result = parse_command(name, arguments)
    assert result.operation == CommandOperation.MEMORY
    assert result.action == action


@pytest.mark.parametrize(
    "arguments",
    [
        "context add unknown value",
        "context add preferred_name",
        "update Abc12345 zero value",
        "update Abc12345 0 value",
        "delete Abc12345",
        "delete Abc12345 -1",
        "clear_mine",
        "recall maybe",
    ],
)
def test_personal_memory_malformed_forms_fail_closed(arguments: str) -> None:
    assert parse_command("memory", arguments).operation == CommandOperation.USAGE


@pytest.mark.parametrize(
    ("name", "arguments", "action"),
    [
        ("export_my_data", "", "export_subject"),
        ("export_group_data", "", "export_group"),
        ("data_summary", "", "summary"),
    ],
)
def test_governance_command_grammar_is_exact(
    name: str, arguments: str, action: str
) -> None:
    result = parse_command(name, arguments)
    assert result.operation == CommandOperation.GOVERNANCE
    assert result.action == action


@pytest.mark.parametrize(
    ("name", "arguments", "action", "value"),
    [
        ("timezone", "status", "timezone_status", None),
        ("timezone", "Asia/Ho_Chi_Minh", "timezone_set", "Asia/Ho_Chi_Minh"),
        ("quiet_hours", "status", "quiet_status", None),
        ("quiet_hours", "off", "quiet_off", None),
        ("quiet_hours", "22:00-08:00", "quiet_set", ("22:00", "08:00")),
        (
            "remind",
            "at 2026-12-01 09:30 pay rent",
            "reminder_once",
            ("2026-12-01", "09:30", "pay rent"),
        ),
        ("remind", "daily 09:30 stretch", "reminder_daily", ("09:30", "stretch")),
        (
            "remind",
            "weekly mon,wed 09:30 stand up",
            "reminder_weekly",
            ("mon,wed", "09:30", "stand up"),
        ),
        ("reminders", "", "reminders_list", None),
        ("cancel_reminder", "ABCDEF234567", "reminder_cancel", "ABCDEF234567"),
        ("checkins", "status", "checkins_status", None),
        ("checkins", "off", "checkins_off", None),
        ("checkins", "on daily 09:30", "checkins_daily", "09:30"),
        ("checkins", "on weekly fri 09:30", "checkins_weekly", ("fri", "09:30")),
    ],
)
def test_scheduling_command_grammar_is_exact(
    name: str, arguments: str, action: str, value: object | None
) -> None:
    result = parse_command(name, arguments)
    assert (result.operation, result.action, result.value) == (
        CommandOperation.SCHEDULING,
        action,
        value,
    )


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("timezone", "Europe/London extra"),
        ("quiet_hours", "24:00-08:00"),
        ("quiet_hours", "08:00-08:00"),
        ("remind", "at tomorrow 09:00 text"),
        ("remind", "daily 24:00 text"),
        ("remind", "weekly mon,mon 09:00 text"),
        ("reminders", "all"),
        ("cancel_reminder", "lowercase1234"),
        ("checkins", "on weekly mon,tue 09:00"),
        ("checkins", "on daily 9:00"),
    ],
)
def test_scheduling_command_malformed_forms_fail_closed(
    name: str, arguments: str
) -> None:
    assert parse_command(name, arguments).operation == CommandOperation.USAGE


def test_ambient_and_sticker_configuration_gates_are_deterministic() -> None:
    participant = ParticipantModel(
        conversation_id=uuid4(), platform_user_id="test-user", display_name="Test"
    )
    ambient = parse_command("mode", "ambient_selective")
    stickers = parse_command("stickers", "on")
    code, change, _ = _configuration_change(
        Settings(_env_file=None), participant, ambient
    )
    assert (code, change) == ("ambient_disabled", None)
    code, change, _ = _configuration_change(
        Settings(_env_file=None), participant, stickers
    )
    assert (code, change) == ("sticker_mapping_unavailable", None)
    code, change, _ = _configuration_change(
        Settings(
            _env_file=None,
            ambient_selective_enabled=True,
            telegram_sticker_mapping={"celebrate": "file-id"},
        ),
        participant,
        ambient,
    )
    assert code == "success" and change is not None
