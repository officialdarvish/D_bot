from __future__ import annotations

from datetime import date, datetime


def _gregorian_to_jalali(gy: int, gm: int, gd: int) -> tuple[int, int, int]:
    """Convert Gregorian date to Jalali/Shamsi date without external deps."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy + 1 if gm > 2 else gy
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        raw = value.strip()
        if not raw or raw in ('-', 'نامحدود', 'None', 'null'):
            return None
        # Accept YYYY-MM-DD, YYYY-MM-DD HH:MM, ISO strings, and date prefix from APIs.
        raw = raw.replace('Z', '+00:00')
        try:
            return datetime.fromisoformat(raw[:19]).date()
        except Exception:
            pass
        try:
            return date.fromisoformat(raw[:10])
        except Exception:
            return None
    return None


def fa_date(value, empty: str = 'نامحدود') -> str:
    d = _coerce_date(value)
    if not d:
        return empty
    jy, jm, jd = _gregorian_to_jalali(d.year, d.month, d.day)
    return f'{jy:04d}/{jm:02d}/{jd:02d}'


def fa_datetime(value, empty: str = '-') -> str:
    if value is None:
        return empty
    if isinstance(value, str):
        raw = value.strip().replace('Z', '+00:00')
        try:
            value = datetime.fromisoformat(raw[:19])
        except Exception:
            return fa_date(raw, empty=empty)
    if isinstance(value, datetime):
        return f'{fa_date(value, empty=empty)} {value.hour:02d}:{value.minute:02d}'
    return fa_date(value, empty=empty)
