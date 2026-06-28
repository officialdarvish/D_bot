
import jwt
import datetime

SECRET = "CHANGE_ME_ENTERPRISE"

def create_token(payload: dict):
    payload["exp"] = datetime.datetime.utcnow() + datetime.timedelta(hours=12)
    return jwt.encode(payload, SECRET, algorithm="HS256")

def verify_token(token: str):
    return jwt.decode(token, SECRET, algorithms=["HS256"])
