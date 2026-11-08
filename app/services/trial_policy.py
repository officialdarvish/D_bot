"""Shared trial availability and duration rules for Telegram and the Mini App."""


def trial_enabled(button_enabled: bool, visible: str, enabled: str) -> bool:
    return bool(button_enabled and visible == '1' and enabled == '1')


def trial_duration(value) -> int:
    try:
        return max(1, int(value or '1'))
    except (TypeError, ValueError):
        return 1
