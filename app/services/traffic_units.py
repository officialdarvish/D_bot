"""Byte-precise quota conversion for fractional gigabyte limits."""

from decimal import Decimal, InvalidOperation

BYTES_PER_GB = 1024 ** 3  # Keep the existing D Bot panel quota convention.


def parse_positive_trial_gb(raw: object) -> Decimal:
    """Accept e.g. 0.1, 0.2, 1.5, 5 and a decimal comma; reject invalid quotas."""
    try:
        value = Decimal(str(raw).strip().replace('٫', '.').replace(',', '.'))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('Trial volume must be a positive number of GB.') from None
    if not value.is_finite() or value <= 0 or value * BYTES_PER_GB < 1:
        raise ValueError('Trial volume must be positive and at least one byte.')
    return value


def format_gb_decimal(value: Decimal) -> str:
    text = format(value, 'f')
    return text.rstrip('0').rstrip('.') if '.' in text else text


def gb_to_bytes(value: object) -> int:
    """Convert GB into bytes without truncating fractional GB to zero."""
    try:
        quantity = Decimal(str(value if value is not None else 0))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('GB volume is invalid.') from None
    if not quantity.is_finite() or quantity < 0:
        raise ValueError('GB volume must be finite and non-negative.')
    byte_count = int(quantity * BYTES_PER_GB)
    if quantity > 0 and byte_count < 1:
        raise ValueError('GB volume is too small to represent in bytes.')
    return byte_count
