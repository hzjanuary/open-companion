"""Deterministic Telegram command grammar and response templates.

This module has no database or provider dependency.  Runtime workers use its
typed result to decide whether a durable command job needs authorization or a
state mutation.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.feedback import FeedbackValue


class CommandOperation(StrEnum):
    READ = "read"
    CONFIGURATION = "configuration"
    PREFERENCE = "preference"
    MEMORY = "memory"
    GOVERNANCE = "governance"
    UNKNOWN = "unknown"
    USAGE = "usage"
    SCHEDULING = "scheduling"
    REGENERATION = "regeneration"
    VOICE = "voice"
    FEEDBACK = "feedback"


@dataclass(frozen=True, slots=True)
class CommandRequest:
    name: str
    operation: CommandOperation
    action: str = "status"
    value: object | None = None


_PROFILE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?(?:@[1-9][0-9]*)?$")
_MODES = {"mention_only", "mention_and_name", "ambient_selective"}
_MEMORY_PUBLIC_ID = re.compile(r"^[A-Za-z0-9]{8,24}$")
_PERSONAL_CONTEXT_KEYS = {
    "preferred_name",
    "preferred_language",
    "response_preference",
    "accessibility_preference",
    "personal_note",
}
_SAFETY_LEVELS = {"strict", "standard", "relaxed"}
_SCHEDULE_PUBLIC_ID = re.compile(r"^[A-Z2-7]{12}$")
_LOCAL_TIME = re.compile(r"^[0-2][0-9]:[0-5][0-9]$")
_LOCAL_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_WEEKDAYS = re.compile(
    r"^(?:mon|tue|wed|thu|fri|sat|sun)(?:,(?:mon|tue|wed|thu|fri|sat|sun))*$"
)


def parse_command(name: str, arguments: str) -> CommandRequest:
    """Parse the complete, intentionally small command grammar."""

    if name in {"start", "help", "status"}:
        return _empty(name, arguments)
    if name == "regenerate":
        return _empty(name, arguments, CommandOperation.REGENERATION, "regenerate")
    if name == "voice":
        return _empty(name, arguments, CommandOperation.VOICE, "voice")
    if name == "feedback":
        if arguments == FeedbackValue.HELPFUL.value:
            return CommandRequest(
                name,
                CommandOperation.FEEDBACK,
                "set",
                FeedbackValue.HELPFUL,
            )
        if arguments == FeedbackValue.UNHELPFUL.value:
            return CommandRequest(
                name,
                CommandOperation.FEEDBACK,
                "set",
                FeedbackValue.UNHELPFUL,
            )
        return _usage(name)
    if name == "quiet" or name == "resume":
        return _empty(name, arguments, CommandOperation.CONFIGURATION, name)
    if name == "mode":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.READ)
        if arguments in _MODES:
            return CommandRequest(
                name, CommandOperation.CONFIGURATION, "mode", arguments
            )
        return _usage(name)
    if name == "frequency":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.READ)
        if arguments in {"low", "normal", "high"}:
            return CommandRequest(
                name, CommandOperation.CONFIGURATION, "frequency", arguments
            )
        return _usage(name)
    if name == "personality":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.READ)
        if arguments == "list":
            return CommandRequest(name, CommandOperation.READ, "list")
        prefix, _, profile = arguments.partition(" ")
        if (
            prefix == "use"
            and profile
            and " " not in profile
            and _PROFILE.fullmatch(profile)
        ):
            return CommandRequest(name, CommandOperation.CONFIGURATION, "use", profile)
        return _usage(name)
    if name in {"stickers", "mentions", "teasing"}:
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.READ)
        if arguments in {"on", "off"}:
            operation = (
                CommandOperation.PREFERENCE
                if name in {"mentions", "teasing"}
                else CommandOperation.CONFIGURATION
            )
            return CommandRequest(name, operation, "set", arguments == "on")
        return _usage(name)
    if name == "memory":
        if not arguments:
            return CommandRequest(name, CommandOperation.MEMORY, "summary")
        if arguments == "list":
            return CommandRequest(name, CommandOperation.MEMORY, "list")
        if arguments == "clear_mine confirm":
            return CommandRequest(name, CommandOperation.MEMORY, "clear_mine")
        if arguments.startswith("recall "):
            action = arguments.removeprefix("recall ")
            if action in {"status", "on", "off"}:
                return CommandRequest(name, CommandOperation.MEMORY, f"recall_{action}")
            return _usage(name)
        if arguments == "reset_group confirm":
            return CommandRequest(name, CommandOperation.MEMORY, "reset_group")
        if arguments.startswith("context add "):
            key, separator, content = arguments.removeprefix("context add ").partition(
                " "
            )
            if separator and key in _PERSONAL_CONTEXT_KEYS and content:
                return CommandRequest(
                    name,
                    CommandOperation.MEMORY,
                    "context_create",
                    (key, content),
                )
            return _usage(name)
        if arguments.startswith("update "):
            parts = arguments.split(" ", 3)
            if (
                len(parts) == 4
                and _MEMORY_PUBLIC_ID.fullmatch(parts[1])
                and parts[2].isdigit()
                and int(parts[2]) > 0
                and parts[3]
            ):
                return CommandRequest(
                    name,
                    CommandOperation.MEMORY,
                    "update",
                    (parts[1], int(parts[2]), parts[3]),
                )
            return _usage(name)
        if arguments.startswith("delete "):
            parts = arguments.split(" ")
            if (
                len(parts) == 3
                and _MEMORY_PUBLIC_ID.fullmatch(parts[1])
                and parts[2].isdigit()
                and int(parts[2]) > 0
            ):
                return CommandRequest(
                    name,
                    CommandOperation.MEMORY,
                    "delete",
                    (parts[1], int(parts[2])),
                )
            return _usage(name)
        prefix, separator, content = arguments.partition(" ")
        if prefix == "remember" and separator and content:
            return CommandRequest(name, CommandOperation.MEMORY, "remember", content)
        return _usage(name)
    if name == "forget":
        return (
            CommandRequest(name, CommandOperation.MEMORY, "forget", arguments)
            if _MEMORY_PUBLIC_ID.fullmatch(arguments)
            else _usage(name)
        )
    if name == "forget_me":
        if not arguments:
            return CommandRequest(name, CommandOperation.MEMORY, "warning")
        return (
            CommandRequest(name, CommandOperation.MEMORY, "confirm")
            if arguments == "confirm"
            else _usage(name)
        )
    if name == "safety":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.READ)
        prefix, separator, rest = arguments.partition(" ")
        if prefix in _SAFETY_LEVELS and not separator:
            return CommandRequest(
                name,
                CommandOperation.CONFIGURATION,
                "set_safety_level",
                prefix,
            )
        if prefix == "teasing" and separator and rest and " " not in rest:
            if rest.isdigit() and 1 <= int(rest) <= 9:
                return CommandRequest(
                    name,
                    CommandOperation.CONFIGURATION,
                    "set_teasing_cap",
                    rest,
                )
        return _usage(name)
    if name in {"protect", "unprotect"}:
        return (
            CommandRequest(
                name, CommandOperation.CONFIGURATION, name, name == "protect"
            )
            if not arguments
            else _usage(name)
        )
    if name == "export_my_data":
        return _empty(name, arguments, CommandOperation.GOVERNANCE, "export_subject")
    if name == "export_group_data":
        return _empty(name, arguments, CommandOperation.GOVERNANCE, "export_group")
    if name == "data_summary":
        return _empty(name, arguments, CommandOperation.GOVERNANCE, "summary")
    if name == "timezone":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.SCHEDULING, "timezone_status")
        if " " not in arguments and len(arguments) <= 64:
            return CommandRequest(
                name, CommandOperation.SCHEDULING, "timezone_set", arguments
            )
        return _usage(name)
    if name == "quiet_hours":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.SCHEDULING, "quiet_status")
        if arguments == "off":
            return CommandRequest(name, CommandOperation.SCHEDULING, "quiet_off")
        start, separator, end = arguments.partition("-")
        if separator and _valid_clock(start) and _valid_clock(end) and start != end:
            return CommandRequest(
                name, CommandOperation.SCHEDULING, "quiet_set", (start, end)
            )
        return _usage(name)
    if name == "remind":
        parts = arguments.split(" ", 3)
        if (
            len(parts) == 4
            and parts[0] == "at"
            and _LOCAL_DATE.fullmatch(parts[1])
            and _valid_clock(parts[2])
            and parts[3]
        ):
            return CommandRequest(
                name,
                CommandOperation.SCHEDULING,
                "reminder_once",
                (parts[1], parts[2], parts[3]),
            )
        parts = arguments.split(" ", 2)
        if (
            len(parts) == 3
            and parts[0] == "daily"
            and _valid_clock(parts[1])
            and parts[2]
        ):
            return CommandRequest(
                name,
                CommandOperation.SCHEDULING,
                "reminder_daily",
                (parts[1], parts[2]),
            )
        parts = arguments.split(" ", 3)
        if (
            len(parts) == 4
            and parts[0] == "weekly"
            and _WEEKDAYS.fullmatch(parts[1])
            and len(set(parts[1].split(","))) == len(parts[1].split(","))
            and _valid_clock(parts[2])
            and parts[3]
        ):
            return CommandRequest(
                name,
                CommandOperation.SCHEDULING,
                "reminder_weekly",
                (parts[1], parts[2], parts[3]),
            )
        return _usage(name)
    if name == "reminders":
        return _empty(name, arguments, CommandOperation.SCHEDULING, "reminders_list")
    if name == "cancel_reminder":
        return (
            CommandRequest(
                name, CommandOperation.SCHEDULING, "reminder_cancel", arguments
            )
            if _SCHEDULE_PUBLIC_ID.fullmatch(arguments)
            else _usage(name)
        )
    if name == "checkins":
        if not arguments or arguments == "status":
            return CommandRequest(name, CommandOperation.SCHEDULING, "checkins_status")
        if arguments == "off":
            return CommandRequest(name, CommandOperation.SCHEDULING, "checkins_off")
        parts = arguments.split(" ")
        if len(parts) == 3 and parts[:2] == ["on", "daily"] and _valid_clock(parts[2]):
            return CommandRequest(
                name, CommandOperation.SCHEDULING, "checkins_daily", parts[2]
            )
        if (
            len(parts) == 4
            and parts[:2] == ["on", "weekly"]
            and parts[2] in {"mon", "tue", "wed", "thu", "fri", "sat", "sun"}
            and _valid_clock(parts[3])
        ):
            return CommandRequest(
                name,
                CommandOperation.SCHEDULING,
                "checkins_weekly",
                (parts[2], parts[3]),
            )
        return _usage(name)
    return CommandRequest(name, CommandOperation.UNKNOWN)


def command_response(
    code: str, *, language: str = "vi", detail: str | None = None
) -> str:
    """Return compact code-owned text; auto language resolves to Vietnamese."""

    english = language == "en"
    templates = {
        "start": (
            "January da san sang. Dung /help de xem lenh.",
            "January is ready. Use /help for commands.",
        ),
        "help": (
            "Xem: /start, /status. Ca nhan: /mentions, /teasing. Quan tri nhom: "
            "/mode, /frequency, /quiet, /resume, /personality, /stickers, "
            "/safety, /protect. Du lieu: /export_my_data, /export_group_data, "
            "/data_summary. Bo nho: /memory. Lich rieng: /timezone, "
            "/quiet_hours, /remind, /reminders, /cancel_reminder, /checkins. "
            "Reply vao cau tra loi va dung /regenerate de tao lai, /voice de nghe, "
            "hoac /feedback helpful|unhelpful de danh gia.",
            "View: /start, /status. Personal: /mentions, /teasing. Group admins: "
            "/mode, /frequency, /quiet, /resume, /personality, /stickers, "
            "/safety, /protect. Data: /export_my_data, /export_group_data, "
            "/data_summary. Memory controls: /memory. Private scheduling: /timezone, "
            "/quiet_hours, /remind, /reminders, /cancel_reminder, /checkins. "
            "Reply to an answer with /regenerate to generate it again, /voice "
            "to listen, or /feedback helpful|unhelpful to rate it.",
        ),
        "regeneration_target_unavailable": (
            "Khong the tao lai cau tra loi nay. Hay reply vao mot cau tra loi hop le.",
            "That answer cannot be regenerated. Reply to an eligible answer.",
        ),
        "regeneration_limit_reached": (
            "Cau tra loi nay da dat gioi han 3 lan tao lai.",
            "This answer has reached the three-regeneration limit.",
        ),
        "voice_target_unavailable": (
            "Khong the doc cau tra loi nay. Hay reply vao mot cau tra loi hop le.",
            "That answer cannot be voiced. Reply to an eligible answer.",
        ),
        "voice_too_long": (
            "Cau tra loi qua dai de doc thanh giong noi.",
            "That answer is too long for voice playback.",
        ),
        "voice_tts_unsupported": (
            "Tinh nang doc giong noi chua san sang.",
            "Voice playback is not available.",
        ),
        "voice_tts_admission_denied": (
            "Chua the tao giong noi luc nay. Hay thu lai sau.",
            "Voice generation is unavailable right now. Try again later.",
        ),
        "voice_tts_generation_failed": (
            "Khong the tao giong noi cho cau tra loi nay.",
            "Could not generate voice for that answer.",
        ),
        "voice_tts_generation_uncertain": (
            "Khong the xac nhan ket qua tao giong noi. Hay gui lenh moi neu can.",
            "Voice generation could not be confirmed. Send a new command if needed.",
        ),
        "feedback_saved": ("Da luu phan hoi.", "Feedback saved."),
        "feedback_no_change": (
            "Phan hoi nay da duoc luu.",
            "Feedback already saved.",
        ),
        "feedback_target_unavailable": (
            "Khong the luu phan hoi cho cau tra loi nay.",
            "Feedback cannot be saved for that answer.",
        ),
        "feedback_limit_reached": (
            "Phan hoi cho cau tra loi nay da dat gioi han thay doi.",
            "Feedback for that answer has reached its change limit.",
        ),
        "usage": ("Cu phap khong hop le. Dung /help.", "Invalid syntax. Use /help."),
        "unknown": (
            "Lenh chua duoc ho tro. Dung /help.",
            "Unsupported command. Use /help.",
        ),
        "denied": (
            "Ban khong duoc phep thay doi cai dat nay.",
            "You are not allowed to change this setting.",
        ),
        "temporary_failure": (
            "Khong the xac minh quyen luc nay. Thu lai sau.",
            "Cannot verify permission now. Try again later.",
        ),
        "success": ("Da cap nhat.", "Updated."),
        "status": ("Trang thai:", "Status:"),
        "unchanged": (
            "Cai dat da dung nhu hien tai.",
            "That setting is already current.",
        ),
        "ambient_disabled": ("Che do nay chua duoc bat.", "That mode is not enabled."),
        "sticker_mapping_unavailable": (
            "Chua co sticker phu hop de bat tinh nang nay.",
            "No deliverable sticker mapping is configured.",
        ),
        "conflict": (
            "Cai dat vua thay doi. Hay kiem tra /status va thu lai.",
            "That setting changed. Check /status and try again.",
        ),
        "safe_failure": (
            "Khong the xu ly lenh nay luc nay.",
            "Cannot process this command right now.",
        ),
        "profile_not_found": (
            "Khong tim thay cau hinh tinh cach dang hoat dong.",
            "The requested active personality was not found.",
        ),
        "profile_not_owned": (
            "Tinh cach nay khong dung cho January nay.",
            "That personality is not available to this January instance.",
        ),
        "memory_summary": (
            "Bo nho chi luu khi ban dung /memory remember. "
            "Pham vi: cuoc tro chuyen nay.",
            "Memory is saved only with /memory remember and stays "
            "in this conversation.",
        ),
        "memory_saved": ("Da luu bo nho.", "Memory saved."),
        "memory_context_saved": (
            "Da luu ngu canh ca nhan.",
            "Personal context saved.",
        ),
        "memory_updated": ("Da cap nhat bo nho.", "Memory updated."),
        "memory_deleted": ("Da xoa bo nho.", "Memory deleted."),
        "memory_missing": (
            "Khong tim thay bo nho dang hoat dong.",
            "No active memory found.",
        ),
        "memory_reset": ("Da xoa bo nho cua nhom.", "Group memories cleared."),
        "memory_cleared": (
            "Da xoa bo nho cua ban trong cuoc tro chuyen nay.",
            "Your memories in this conversation were cleared.",
        ),
        "memory_conflict": (
            "Bo nho da thay doi. Hay xem /memory list va thu lai.",
            "That memory changed. Run /memory list and try again.",
        ),
        "memory_context_private": (
            "Ngu canh ca nhan chi duoc quan ly trong tro chuyen rieng.",
            "Personal context is available only in a private conversation.",
        ),
        "memory_recall_enabled": (
            "Goi lai bo nho dang bat.",
            "Memory recall is enabled.",
        ),
        "memory_recall_disabled": (
            "Goi lai bo nho dang tat.",
            "Memory recall is disabled.",
        ),
        "memory_private_reset": (
            "Lenh nay chi dung trong nhom.",
            "This command is available only in groups.",
        ),
        "forget_me_warning": (
            "Xac nhan bang /forget_me confirm. January se xoa/an danh hoa ho so va "
            "noi dung cua ban tai ket noi nay; tin da gui va yeu cau nha cung cap "
            "khong the thu hoi.",
            "Confirm with /forget_me confirm. January will erase/anonymize your "
            "profile and authored content for this connection; delivered messages "
            "and provider requests cannot be retracted.",
        ),
        "forget_me_done": (
            "Da xu ly yeu cau xoa du lieu.",
            "Your deletion request has been processed.",
        ),
        "forget_me_unchanged": (
            "Yeu cau xoa du lieu da duoc xu ly truoc do.",
            "Your deletion request was already processed.",
        ),
        "member_missing": (
            "Reply vao tin nhan cua thanh vien can quan ly.",
            "Reply to the member you want to manage.",
        ),
        "protect_done": (
            "Da bao ve thanh vien nay; January se khong nham vao ho.",
            "This member is now protected; January will not target them.",
        ),
        "unprotect_done": (
            "Da go bao ve cho thanh vien nay.",
            "Protection removed for this member.",
        ),
        "export_requested": (
            "Yeu cau xuat du lieu da duoc tiep nhan. Ma yeu cau:",
            "Data export requested. Request ID:",
        ),
        "export_group_private": (
            "Lenh nay chi dung trong nhom.",
            "This command is available only in groups.",
        ),
        "governance_disabled": (
            "Tinh nang quan tri du lieu chua duoc bat.",
            "Data governance is not enabled.",
        ),
        "export_failed": (
            "Khong the tao yeu cau xuat du lieu.",
            "Could not create the data export request.",
        ),
        "data_summary": (
            "Tom tat du lieu duoc January luu tru:",
            "Data stored by January:",
        ),
        "schedule_private": (
            "Lenh lich chi dung trong tro chuyen rieng.",
            "Scheduling commands are available only in private conversations.",
        ),
        "schedule_disabled": (
            "Tinh nang lich chua duoc bat.",
            "Scheduling is not enabled.",
        ),
        "schedule_timezone_required": (
            "Hay dat mui gio IANA truoc bang /timezone, vi du Asia/Ho_Chi_Minh.",
            "Set an IANA timezone first with /timezone, for example Europe/London.",
        ),
        "schedule_timezone_invalid": (
            "Mui gio khong hop le. Dung ten IANA, vi du Asia/Ho_Chi_Minh.",
            "Invalid timezone. Use an IANA name, for example Europe/London.",
        ),
        "schedule_created": ("Da tao lich.", "Schedule created."),
        "schedule_cancelled": ("Da huy loi nhac.", "Reminder cancelled."),
        "schedule_not_found": (
            "Khong tim thay loi nhac dang hoat dong.",
            "No active reminder was found.",
        ),
        "schedule_limit": (
            "Da dat gioi han 10 loi nhac dang hoat dong.",
            "The limit of 10 active reminders has been reached.",
        ),
        "schedule_too_late": (
            "Thoi diem qua gan, da qua, hoac vuot qua 365 ngay.",
            "That time is too soon, in the past, or beyond 365 days.",
        ),
        "schedule_status": ("Lich cua ban:", "Your schedule:"),
        "schedule_checkins_on": ("Da bat hoi tham.", "Check-ins enabled."),
        "schedule_checkins_off": ("Da tat hoi tham.", "Check-ins disabled."),
        "schedule_checkin": (
            "January dang hoi tham ban. Hom nay ban the nao?",
            "January is checking in. How are you doing today?",
        ),
        "schedule_reminder": ("Nhac nho:", "Reminder:"),
    }
    base = templates.get(code, templates["safe_failure"])[1 if english else 0]
    return f"{base} {detail}" if detail else base


def _empty(
    name: str,
    arguments: str,
    operation: CommandOperation = CommandOperation.READ,
    action: str = "status",
) -> CommandRequest:
    return CommandRequest(name, operation, action) if not arguments else _usage(name)


def _usage(name: str) -> CommandRequest:
    return CommandRequest(name, CommandOperation.USAGE)


def _valid_clock(value: str) -> bool:
    if _LOCAL_TIME.fullmatch(value) is None:
        return False
    return int(value[:2]) < 24
