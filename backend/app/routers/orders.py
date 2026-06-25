
from fastapi import APIRouter

router = APIRouter(prefix="/orders")

@router.get("/")
def orders():
    return [
        {"id": 1, "user": "Ali", "amount": 12, "status": "completed"},
        {"id": 2, "user": "Sara", "amount": 8, "status": "pending"},
    ]
