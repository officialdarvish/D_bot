"""Purchased-panel billing eligibility, independent of public/reseller sales scope.

Never infer prepaid allocations from a server policy: only an explicit volume
profile owns that ledger. Ambiguous legacy orders remain untouched for review.
"""


def panel_billing_mode(meta, gb_price, hourly_price, finance):
    if finance.get('transition'):
        return None
    modes = (meta or {}).get('reseller_billing_modes', ['volume'])
    if isinstance(modes, str):
        modes = [value.strip() for value in modes.split(',')]
    mode = finance.get('billing_mode')
    if mode == 'volume':
        return 'volume' if 'volume' in modes else None
    if mode not in (None, 'payg'):
        return None
    # A legacy meter alone, a server's sales scope, or an empty financial
    # profile must never turn an ordinary volume server into PAYG.
    if 'payg' in modes and (int(gb_price or 0) > 0 or int(hourly_price or 0) > 0):
        return 'payg'
    return None
