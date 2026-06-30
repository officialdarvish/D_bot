from aiogram.fsm.state import State, StatesGroup

class BuyFlow(StatesGroup):
    server_id = State()
    category_id = State()
    plan_id = State()
    username = State()
    password = State()
    payment_method = State()
    receipt = State()

class TicketFlow(StatesGroup):
    subject = State()
    message = State()

class QueryClient(StatesGroup):
    server_id = State()
    username = State()
    password = State()

class AdminTicketReply(StatesGroup):
    ticket_id = State()
    message = State()

class WalletTopupFlow(StatesGroup):
    wallet_type = State()
    amount = State()
    receipt = State()



class ResellerCreateUser(StatesGroup):
    username = State()
    volume = State()
    duration = State()

class ResellerTopupFlow(StatesGroup):
    package_id = State()
    receipt = State()

class DiscountInput(StatesGroup):
    code = State()

class ResellerDiscountInput(StatesGroup):
    code = State()


class ResellerRenewUser(StatesGroup):
    service_id = State()
    volume = State()
    duration = State()
