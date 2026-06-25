
from fastapi import APIRouter

router = APIRouter(prefix="/metrics")

@router.get("/")
def metrics():
    return {
        "revenue": 31240.90,
        "users": 9421,
        "orders": 1520,
        "servers": 168,
        "growth": {
            "revenue": 18.2,
            "users": 11.4
        }
    }
