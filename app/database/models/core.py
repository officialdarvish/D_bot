from datetime import datetime
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Numeric, JSON, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.database.base import Base

class User(Base):
    __tablename__ = 'users'
    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(128), nullable=True)
    full_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    wallet_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    wallet_v2ray_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    wallet_openvpn_balance: Mapped[int] = mapped_column(BigInteger, default=0)
    accepted_rules: Mapped[bool] = mapped_column(Boolean, default=False)
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[str | None] = mapped_column(String(64), unique=True, index=True, nullable=True)
    referred_by_user_id: Mapped[int | None] = mapped_column(ForeignKey('users.id', ondelete='SET NULL'), nullable=True)
    referral_joined_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ServerCategory(Base):
    __tablename__ = 'server_categories'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    server_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class Server(Base):
    __tablename__ = 'servers'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    server_type: Mapped[str] = mapped_column(String(32)) # xui, openvpn, pasargad
    panel_url: Mapped[str] = mapped_column(Text)
    subscription_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    username: Mapped[str] = mapped_column(String(255))
    password_encrypted: Mapped[str] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('server_categories.id'), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Plan(Base):
    __tablename__ = 'plans'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    volume_gb: Mapped[int] = mapped_column(Integer, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    price_irt: Mapped[int] = mapped_column(BigInteger)
    category_id: Mapped[int | None] = mapped_column(ForeignKey('server_categories.id'), nullable=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    inbound_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_unlimited: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)

class DiscountCode(Base):
    __tablename__ = 'discount_codes'
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(80), unique=True)
    discount_type: Mapped[str] = mapped_column(String(16)) # percent, fixed
    value: Mapped[int] = mapped_column(BigInteger)
    max_uses: Mapped[int] = mapped_column(Integer, default=1)
    per_user_limit: Mapped[int] = mapped_column(Integer, default=1)
    allowed_server_ids: Mapped[list] = mapped_column(JSON, default=list)
    used_count: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class DiscountUsage(Base):
    __tablename__ = 'discount_usages'
    id: Mapped[int] = mapped_column(primary_key=True)
    discount_id: Mapped[int] = mapped_column(ForeignKey('discount_codes.id', ondelete='CASCADE'))
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    source: Mapped[str] = mapped_column(String(32), default='buy')
    used_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class PaymentCard(Base):
    __tablename__ = 'payment_cards'
    id: Mapped[int] = mapped_column(primary_key=True)
    server_type: Mapped[str] = mapped_column(String(32))
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    card_number: Mapped[str] = mapped_column(String(32))
    owner_name: Mapped[str] = mapped_column(String(150))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class ClientService(Base):
    __tablename__ = 'client_services'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    reseller_id: Mapped[int | None] = mapped_column(ForeignKey('reseller_accounts.id', ondelete='SET NULL'), nullable=True)
    reseller_reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    reseller_lifetime_used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    plan_id: Mapped[int | None] = mapped_column(ForeignKey('plans.id'), nullable=True)
    purchase_category_id: Mapped[int | None] = mapped_column(ForeignKey('server_categories.id', ondelete='SET NULL'), nullable=True)
    client_username: Mapped[str] = mapped_column(String(150), index=True)
    xui_email: Mapped[str] = mapped_column(String(150), index=True)
    xui_uuid: Mapped[str | None] = mapped_column(String(80), nullable=True)
    inbound_ids: Mapped[list] = mapped_column(JSON, default=list)
    sub_link: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    traffic_baseline_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_1gb_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_100mb_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_24h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_2h_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_20m_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    disabled_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    disabled_notify_count: Mapped[int] = mapped_column(Integer, default=0)
    disabled_last_notified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('server_id', 'client_username', name='uq_server_client_username'),)



class ResellerAccount(Base):
    __tablename__ = 'reseller_accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True, index=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    total_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    used_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ResellerServiceActivity(Base):
    __tablename__ = 'reseller_service_activities'
    id: Mapped[int] = mapped_column(primary_key=True)
    reseller_id: Mapped[int] = mapped_column(ForeignKey('reseller_accounts.id', ondelete='CASCADE'), index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey('client_services.id', ondelete='SET NULL'), nullable=True, index=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id', ondelete='SET NULL'), nullable=True)
    action: Mapped[str] = mapped_column(String(32), index=True)
    event_key: Mapped[str] = mapped_column(String(180), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(150))
    volume_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    previous_volume_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    duration_days: Mapped[int] = mapped_column(Integer, default=0)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


class ResellerAccessRequest(Base):
    __tablename__ = 'reseller_access_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(32), default='pending')  # pending, approved, rejected
    reviewed_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ResellerPackage(Base):
    __tablename__ = 'reseller_packages'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(150))
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    volume_gb: Mapped[int] = mapped_column(Integer, default=0)
    price_irt: Mapped[int] = mapped_column(BigInteger, default=0)
    reseller_validity_days: Mapped[int] = mapped_column(Integer, default=365)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class OpenVPNProfile(Base):
    __tablename__ = 'openvpn_profiles'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(150))
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id', ondelete='SET NULL'), nullable=True)
    file_name: Mapped[str] = mapped_column(String(255), default='profile.ovpn')
    content: Mapped[str] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class ResellerBuildConfig(Base):
    __tablename__ = 'reseller_build_configs'
    id: Mapped[int] = mapped_column(primary_key=True)
    server_id: Mapped[int | None] = mapped_column(ForeignKey('servers.id'), nullable=True)
    inbound_ids: Mapped[list] = mapped_column(JSON, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class ResellerTopupRequest(Base):
    __tablename__ = 'reseller_topup_requests'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    reseller_id: Mapped[int | None] = mapped_column(ForeignKey('reseller_accounts.id', ondelete='SET NULL'), nullable=True)
    package_id: Mapped[int | None] = mapped_column(ForeignKey('reseller_packages.id'), nullable=True)
    amount_irt: Mapped[int] = mapped_column(BigInteger, default=0)
    volume_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    receipt_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default='pending')
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Order(Base):
    __tablename__ = 'orders'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    plan_id: Mapped[int | None] = mapped_column(ForeignKey('plans.id'), nullable=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey('client_services.id', ondelete='SET NULL'), nullable=True)
    amount_irt: Mapped[int] = mapped_column(BigInteger)
    payment_method: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(32), default='pending')
    receipt_file_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_payment_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    external_invoice_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejected_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class WalletTransaction(Base):
    __tablename__ = 'wallet_transactions'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    amount_irt: Mapped[int] = mapped_column(BigInteger)
    tx_type: Mapped[str] = mapped_column(String(32))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Ticket(Base):
    __tablename__ = 'tickets'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    subject: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(32), default='open')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class TicketMessage(Base):
    __tablename__ = 'ticket_messages'
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket_id: Mapped[int] = mapped_column(ForeignKey('tickets.id'))
    sender_type: Mapped[str] = mapped_column(String(16))
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Setting(Base):
    __tablename__ = 'settings'
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value: Mapped[str] = mapped_column(Text)

class TestAccountUsage(Base):
    __tablename__ = 'test_account_usages'
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey('users.id'))
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    service_id: Mapped[int | None] = mapped_column(ForeignKey('client_services.id', ondelete='SET NULL'), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class TestAccountCounter(Base):
    """Persistent, concurrency-safe sequence for readable test client names."""
    __tablename__ = 'test_account_counters'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)


class ServiceUsernameCounter(Base):
    """Global sequence used only when a requested service username is duplicated."""
    __tablename__ = 'service_username_counters'
    id: Mapped[int] = mapped_column(primary_key=True, default=1)
    next_number: Mapped[int] = mapped_column(BigInteger, default=1, nullable=False)
