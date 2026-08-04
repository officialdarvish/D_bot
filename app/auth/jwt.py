import datetime
import os

import jwt


def _jwt_secret() -> str:
    secret = (
        os.getenv("JWT_SECRET")
        or os.getenv("FERNET_KEY")
        or os.getenv("BOT_TOKEN")
        or ""
    ).strip()
    if not secret:
        raise RuntimeError("JWT_SECRET, FERNET_KEY or BOT_TOKEN must be configured before issuing JWT tokens.")
    return secret


def create_token(payload: dict):
    data = dict(payload)
    data["exp"] = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    return jwt.encode(data, _jwt_secret(), algorithm="HS256")


def verify_token(token: str):
    return jwt.decode(token, _jwt_secret(), algorithms=["HS256"])
