from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, Integer, JSON
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

class ResellerUsageMeter(Base):
    __tablename__='reseller_usage_meters'
    id:Mapped[int]=mapped_column(primary_key=True)
    reseller_id:Mapped[int]=mapped_column(ForeignKey('reseller_accounts.id',ondelete='RESTRICT'),index=True)
    service_id:Mapped[int]=mapped_column(Integer,unique=True,index=True)
    server_id:Mapped[int|None]=mapped_column(Integer,nullable=True,index=True)
    checkpoint_bytes:Mapped[int]=mapped_column(BigInteger,default=0)
    remainder:Mapped[int]=mapped_column(BigInteger,default=0)
    rate_irt_per_gb:Mapped[int]=mapped_column(BigInteger,default=0)
    suspended:Mapped[bool]=mapped_column(Boolean,default=False)
    suspension_pending:Mapped[bool]=mapped_column(Boolean,default=False)
    last_error:Mapped[str|None]=mapped_column(Text,nullable=True)
    last_billed_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)

class ResellerBillingEntry(Base):
    __tablename__='reseller_billing_entries'
    id:Mapped[int]=mapped_column(primary_key=True)
    reseller_id:Mapped[int]=mapped_column(ForeignKey('reseller_accounts.id',ondelete='RESTRICT'),index=True)
    server_id:Mapped[int|None]=mapped_column(Integer,nullable=True,index=True)
    service_id:Mapped[int|None]=mapped_column(Integer,nullable=True)
    event_key:Mapped[str]=mapped_column(String(180),unique=True,index=True)
    kind:Mapped[str]=mapped_column(String(40),index=True)
    amount_irt:Mapped[int]=mapped_column(BigInteger)
    balance_after_irt:Mapped[int]=mapped_column(BigInteger)
    usage_bytes:Mapped[int]=mapped_column(BigInteger,default=0)
    rate_irt_per_gb:Mapped[int]=mapped_column(BigInteger,default=0)
    note:Mapped[str]=mapped_column(Text,default='')
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow,index=True)

class ResellerWalletReceipt(Base):
    __tablename__='reseller_wallet_receipts'
    id:Mapped[int]=mapped_column(primary_key=True)
    reseller_id:Mapped[int]=mapped_column(ForeignKey('reseller_accounts.id',ondelete='RESTRICT'),index=True)
    amount_irt:Mapped[int]=mapped_column(BigInteger)
    file_id:Mapped[str]=mapped_column(Text)
    is_photo:Mapped[bool]=mapped_column(Boolean,default=False)
    status:Mapped[str]=mapped_column(String(20),default='pending')
    reviewed_by:Mapped[int|None]=mapped_column(BigInteger,nullable=True)
    created_at:Mapped[datetime]=mapped_column(DateTime,default=datetime.utcnow)
