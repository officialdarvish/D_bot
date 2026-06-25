
from fastapi import APIRouter

router = APIRouter(prefix="/auth")

@router.post("/login")
def login():
    return {
        "token": "mock-jwt-token",
        "role": "admin"
    }
