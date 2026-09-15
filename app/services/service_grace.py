from __future__ import annotations

from datetime import datetime, timedelta

SERVICE_RENEWAL_GRACE = timedelta(hours=72)

# Only services that actually ended or disappeared from the upstream panel are
# automatically purged after the renewal grace period. A user/admin manually
# disabling a service must not silently delete it three days later.
AUTO_PURGE_DISABLED_REASONS = {
    'expired',
    'volume',
    'missing_on_panel',
    # Backward compatibility for records created by older releases.
    'panel',
}


def is_tombstone(service) -> bool:
    if service is None:
        return True
    return str(getattr(service, 'client_username', '') or '').startswith('deleted_')


def local_terminal_reason(service, now: datetime | None = None) -> str | None:
    """Return why a service has actually ended based on stored quota/date."""
    if service is None or is_tombstone(service):
        return None
    now = now or datetime.utcnow()
    expires_at = getattr(service, 'expires_at', None)
    if expires_at is not None and expires_at <= now:
        return 'expired'
    total = int(getattr(service, 'total_bytes', 0) or 0)
    used = int(getattr(service, 'used_bytes', 0) or 0)
    if total > 0 and used >= total:
        return 'volume'
    return None


def mark_service_active(service) -> None:
    service.is_active = True
    service.disabled_at = None
    service.disabled_reason = None
    service.disabled_notify_count = 0
    service.disabled_last_notified_at = None


def mark_service_disabled(
    service,
    now: datetime | None = None,
    *,
    reason: str | None = None,
) -> str:
    """Mark a service inactive and start its 72-hour renewal window once.

    For date-expired services, the known expiry timestamp is the most accurate
    start of the grace period. For quota exhaustion (whose exact second is not
    available from every panel), the first successful detection time is used.
    """
    now = now or datetime.utcnow()
    resolved_reason = reason or local_terminal_reason(service, now) or 'disabled_on_panel'
    previous_reason = getattr(service, 'disabled_reason', None)
    service.is_active = False
    service.disabled_reason = resolved_reason
    entering_terminal_state = (
        resolved_reason in AUTO_PURGE_DISABLED_REASONS
        and previous_reason not in AUTO_PURGE_DISABLED_REASONS
    )
    if getattr(service, 'disabled_at', None) is None or entering_terminal_state:
        expires_at = getattr(service, 'expires_at', None)
        if resolved_reason == 'expired' and expires_at is not None and expires_at <= now:
            service.disabled_at = expires_at
        else:
            service.disabled_at = now
    service.disabled_notify_count = int(getattr(service, 'disabled_notify_count', 0) or 0)
    return resolved_reason


def is_auto_purge_service(service, now: datetime | None = None) -> bool:
    # A service may have been manually disabled first and then genuinely expire
    # later. The current quota/date state must take precedence over the old
    # manual-disable label.
    reason = local_terminal_reason(service, now) or getattr(service, 'disabled_reason', None)
    return reason in AUTO_PURGE_DISABLED_REASONS


def grace_deadline(service, now: datetime | None = None) -> datetime | None:
    if service is None or bool(getattr(service, 'is_active', False)):
        return None
    if not is_auto_purge_service(service, now):
        return None
    started_at = getattr(service, 'disabled_at', None)
    if started_at is None:
        return None
    return started_at + SERVICE_RENEWAL_GRACE


def visible_in_my_services(service, now: datetime | None = None) -> bool:
    """Whether an owned service must remain in the user's My Configs list."""
    if service is None or is_tombstone(service):
        return False
    if bool(getattr(service, 'is_active', False)):
        return True
    # Manual disable is not an expiry event and remains manageable indefinitely.
    if not is_auto_purge_service(service, now):
        return True
    deadline = grace_deadline(service, now)
    # Missing tracking must never make a service disappear. The caller can
    # backfill disabled_at and commit it immediately.
    if deadline is None:
        return True
    return (now or datetime.utcnow()) < deadline
