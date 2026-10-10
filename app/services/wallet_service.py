from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import User, WalletTransaction

class WalletService:
    async def add_balance(self, session: AsyncSession, user: User, amount: int, description: str):
        user.wallet_balance += amount
        session.add(WalletTransaction(user_id=user.id, amount_irt=amount, tx_type='credit', description=description))
        await session.commit()

    async def charge(self, session: AsyncSession, user: User, amount: int, description: str) -> bool:
        if user.wallet_balance < amount:
            return False
        user.wallet_balance -= amount
        session.add(WalletTransaction(user_id=user.id, amount_irt=-amount, tx_type='debit', description=description))
        await session.commit()
        return True
