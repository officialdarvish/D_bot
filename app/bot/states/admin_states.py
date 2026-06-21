from aiogram.fsm.state import State, StatesGroup

class AddServer(StatesGroup):
    server_type = State()
    category = State()
    name = State()
    panel_url = State()
    panel_path = State()
    subscription_url = State()
    username = State()
    password = State()
    inbound_ids = State()
    confirm = State()

class AddCategory(StatesGroup):
    server_id = State()
    name = State()

class EditCategory(StatesGroup):
    category_id = State()
    name = State()

class PaymentCardConfig(StatesGroup):
    card_number = State()
    owner_name = State()
    server_id = State()
    edit_value = State()

class PaymentTextConfig(StatesGroup):
    text = State()

class AddPlan(StatesGroup):
    title = State()
    volume = State()
    duration = State()
    price = State()
    category_id = State()
    inbound_ids = State()

class EditPlan(StatesGroup):
    value = State()

class WalletChange(StatesGroup):
    telegram_id = State()
    mode = State()
    amount = State()

class Broadcast(StatesGroup):
    message = State()

class TestAccountConfig(StatesGroup):
    server_id = State()
    inbound_ids = State()
    volume = State()
    duration = State()

class WelcomeTextConfig(StatesGroup):
    text = State()

class ChannelConfig(StatesGroup):
    url = State()


class RulesTextConfig(StatesGroup):
    text = State()

class PaygRate(StatesGroup):
    amount = State()

class BroadcastFlow(StatesGroup):
    message = State()


class RestoreBackup(StatesGroup):
    file = State()


class ServiceTypeConfig(StatesGroup):
    value = State()


class AntiSharingConfig(StatesGroup):
    value = State()


class AddResellerPackage(StatesGroup):
    title = State()
    server_id = State()
    volume = State()
    price = State()
    validity_days = State()

class EditResellerPackage(StatesGroup):
    value = State()

class ExtendReseller(StatesGroup):
    days = State()

class ResellerServerForm(StatesGroup):
    name = State()
    panel_url = State()
    panel_path = State()
    subscription_url = State()
    username = State()
    password = State()
    inbound_ids = State()
    confirm = State()

class AdjustResellerVolume(StatesGroup):
    telegram_id = State()
    amount = State()

class AddDiscountCode(StatesGroup):
    code = State()
    discount_type = State()
    value = State()
    max_uses = State()
    per_user_limit = State()

class EditDiscountCode(StatesGroup):
    value = State()
    max_uses = State()
    per_user_limit = State()
