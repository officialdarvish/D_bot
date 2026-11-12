"""Recognize Telegram transport timeouts without swallowing provider failures."""
import asyncio
import httpx

def telegram_timeout(exc,context=''):
    seen=set();telegram='telegram' in context.lower();timeout=False
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc));name=type(exc).__name__.lower();message=str(exc).lower()
        telegram=telegram or 'telegram' in name or 'api.telegram.org' in message
        timeout=timeout or isinstance(exc,(TimeoutError,asyncio.TimeoutError,httpx.TimeoutException)) or 'timeout' in name or 'timeout' in message or 'timed out' in message
        exc=exc.__cause__ or exc.__context__
    return bool(telegram and timeout)
