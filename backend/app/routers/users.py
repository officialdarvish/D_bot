
from fastapi import APIRouter

router = APIRouter(prefix="/users")

@router.get("/")
def users():
    return [
        {"id": 1, "name": "Admin", "role": "admin"},
        {"id": 2, "name": "Ali", "role": "user"},
    ]
