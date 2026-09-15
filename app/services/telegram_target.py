from __future__ import annotations

import re
from urllib.parse import urlparse

_NUMERIC_CHAT_ID_RE = re.compile(r"^-?\d+$")


def _as_telegram_url(value: str) -> str:
    raw = (value or "").strip()
    lowered = raw.lower()
    if lowered.startswith(("https://", "http://")):
        return raw
    if lowered.startswith(("t.me/", "telegram.me/", "www.t.me/", "www.telegram.me/")):
        return "https://" + raw
    return ""


def is_private_invite_link(value: str) -> bool:
    """Return True for Telegram invite links that Bot API cannot use as chat_id.

    Examples:
      https://t.me/+AbCdEf...
      https://t.me/joinchat/AbCdEf...
    """
    url = _as_telegram_url(value)
    if not url:
        raw = (value or "").strip()
        return raw.startswith("+") or raw.lower().startswith("joinchat/")
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"t.me", "telegram.me"}:
        return False
    path = parsed.path.strip("/")
    return path.startswith("+") or path.lower().startswith("joinchat/")


def normalize_telegram_target(destination: str, value: str, default_bot_chat_id: str = "") -> str:
    """Normalize Telegram destinations accepted by getChat/sendMessage.

    Supported forms:
      @public_channel
      https://t.me/public_channel
      -1001234567890
      https://t.me/c/1234567890/25  -> -1001234567890

    Private invite links are deliberately preserved so the caller can return a
    precise validation error. Telegram Bot API cannot resolve t.me/+... links.
    """
    raw = (value or "").strip()
    if destination == "bot" and not raw:
        return (default_bot_chat_id or "").strip()
    if not raw:
        return ""

    if _NUMERIC_CHAT_ID_RE.fullmatch(raw) or raw.startswith("@"):
        return raw

    url = _as_telegram_url(raw)
    if not url:
        return raw

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    if host not in {"t.me", "telegram.me"}:
        return raw

    parts = [part for part in parsed.path.split("/") if part]
    if not parts:
        return raw

    # Private channel/supergroup message links contain the internal numeric id.
    # Bot API chat_id is the same number with the -100 prefix.
    if parts[0].lower() == "c" and len(parts) >= 2 and parts[1].isdigit():
        internal_id = parts[1]
        return f"-100{internal_id}"

    first = parts[0]
    if first.startswith("+") or first.lower() == "joinchat":
        return raw

    # Public message links such as t.me/channel/42 resolve by @channel.
    return first if first.startswith("@") else "@" + first


def private_target_help() -> str:
    return (
        "Private invite links (t.me/+... or t.me/joinchat/...) cannot be used as a Bot API chat ID. "
        "Paste the numeric chat ID (-100...) or copy the link of any post inside the private "
        "channel/group (https://t.me/c/.../...) instead. Make sure the bot is an administrator."
    )


def resolve_telegram_target(
    destination: str,
    value: str,
    *,
    detected_chat_id: str = "",
    detected_chat_type: str = "",
    default_bot_chat_id: str = "",
) -> str:
    """Return a usable target, falling back to an auto-detected private chat ID."""
    normalized = normalize_telegram_target(destination, value, default_bot_chat_id=default_bot_chat_id)
    if destination not in {"channel", "group"} or not is_private_invite_link(normalized):
        return normalized
    detected = (detected_chat_id or "").strip()
    detected_type = (detected_chat_type or "").strip().lower()
    type_ok = (destination == "channel" and detected_type == "channel") or (
        destination == "group" and detected_type in {"group", "supergroup"}
    )
    return detected if detected and type_ok else normalized
