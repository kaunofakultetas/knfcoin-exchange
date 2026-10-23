############################################################
#  [*] The API as the SPA reads it
#
#  The backend's written copy of its contract with the React
#  frontend (vite/app): for every answer the pages consume,
#  each field they read and the JSON type it must have. The
#  pages compute with the numbers as they come — amounts in
#  whole coins, times in epoch milliseconds (the countdown
#  subtracts the browser's clock from expires_at), counts as
#  integers — test the nullable fields for null, index the
#  rates, the limits and the coin logos by the asset labels
#  the swap form shows, compare the status with the nine
#  strings their lib/orders.js knows, draw each coin's logo
#  from the URL its answer advertises, list the refunds an
#  order carries with who each one pays what, cap the swap
#  form's amount at what the exchange can still pay out, and
#  show the error field of a failed answer word for word.
#
#  The frontend's suite holds the same contract from its side,
#  in its test double (vite/app/tests/support/backend). The
#  two suites share no file on purpose, so a change here is a
#  change the frontend must be told about — and its double
#  updated to match.
#
#  Each checker returns the list of what is wrong with one
#  answer (empty when it reads as the pages expect), so a
#  failing test names every broken field at once.
#
#  Used by:
#    - tests/test_api_contract.py — the Flask app's answers
#    - tests/integration/test_live_smoke.py — the running
#      backend's answers (opt-in)
############################################################


# The asset labels the swap form shows, sends and indexes the
# rates and the limits by
ASSETS = ('KNF Coin', 'LTC Testnet')

# The rate keys the pages look up, one per direction
PAIR_KEYS = ('KNF Coin->LTC Testnet', 'LTC Testnet->KNF Coin')

# Every status the order page and the badges know
STATUSES = ('awaiting_deposit', 'awaiting_confirmations', 'exchanging', 'sending',
            'completed', 'expired', 'refunding', 'refunded', 'failed', 'reversed')

# Times before 2001-09-09 in milliseconds are below this — a
# time sent in seconds would land there
EPOCH_MS_FLOOR = 10 ** 12


# The JSON types, each a name for the report and a test
TEXT = ('text', lambda v: isinstance(v, str))
NUMBER = ('a number', lambda v: isinstance(v, (int, float)) and not isinstance(v, bool))
POSITIVE = ('a positive number', lambda v: NUMBER[1](v) and v > 0)
INTEGER = ('an integer', lambda v: isinstance(v, int) and not isinstance(v, bool))
BOOLEAN = ('true or false', lambda v: isinstance(v, bool))
LIST = ('a list', lambda v: isinstance(v, list))
EPOCH_MS = ('epoch milliseconds', lambda v: INTEGER[1](v) and v > EPOCH_MS_FLOOR)
ASSET = ('an asset label', lambda v: v in ASSETS)
STATUS = ('a known status', lambda v: v in STATUSES)
TEXT_OR_NULL = ('text or null', lambda v: v is None or TEXT[1](v))
NUMBER_OR_NULL = ('a number or null', lambda v: v is None or NUMBER[1](v))

# A coin's logo: the URL the backend serves it at, or null for
# a coin without a logo file (the page then draws its dot)
ICON = ('a logo URL or null', lambda v: v is None or (TEXT[1](v) and v.startswith('/api/exchange/icons/')))


# An order row, as ExchangeApi camelizes it for the exchange
# and the order page (other columns may come along; the pages
# ignore them)
ORDER_FIELDS = {
    'id': TEXT,
    'pair': TEXT,
    'from_asset': ASSET,
    'to_asset': ASSET,
    'from_amount': NUMBER,
    'to_amount': NUMBER,
    'rate': NUMBER,
    'locked_rate': NUMBER_OR_NULL,
    'destination': TEXT,
    'status': STATUS,
    'confirm_target': INTEGER,
    'confirm_count': INTEGER,
    'deposit_address': TEXT,
    'deposit_scripthash': TEXT,
    'received_amount': NUMBER,
    'tx_deposit_id': TEXT_OR_NULL,
    'tx_send_id': TEXT_OR_NULL,
    'error': TEXT_OR_NULL,
    'from_icon': ICON,
    'to_icon': ICON,
    'refunds': LIST,
    'created_at': EPOCH_MS,
    'updated_at': EPOCH_MS,
    'expires_at': EPOCH_MS,
}

# One refund of an order, as the order page lists it
REFUND_FIELDS = {
    'txid': TEXT,
    'confirmed': BOOLEAN,
    'created_at': EPOCH_MS,
    'recipients': LIST,
}

# One sender a refund pays back, in whole coins — the address
# null for a script the exchange cannot name
RECIPIENT_FIELDS = {
    'address': TEXT_OR_NULL,
    'amount': POSITIVE,
}

# One reserve wallet, as ExchangeApi camelizes it for the
# reserves page
RESERVE_FIELDS = {
    'network': TEXT,
    'asset': ASSET,
    'short_name': TEXT,
    'full_name': TEXT,
    'block_explorer': TEXT_OR_NULL,
    'icon': ICON,
    'address': TEXT,
    'confirmed': NUMBER_OR_NULL,
    'unconfirmed': NUMBER_OR_NULL,
    'available': NUMBER_OR_NULL,
    'error': TEXT_OR_NULL,
}








############################################################
# field_problems
############################################################
#
# Every field of `fields` the answer lacks or carries with the
# wrong JSON type, as one sentence each. An answer that is not
# an object at all is one problem on its own.
#
# Used by:
#   - order_problems, reserve_problems (below)
############################################################

def field_problems(answer, fields, what):
    if not isinstance(answer, dict):
        return [f'{what} is not an object: {answer!r}']

    problems = []
    for field, (kind, test) in fields.items():
        if field not in answer:
            problems.append(f'{what} lacks {field}')
        elif not test(answer[field]):
            problems.append(f'{what}.{field} should be {kind}, got {answer[field]!r}')
    return problems








############################################################
# order_problems
############################################################
#
# What is wrong with an order answer: it must carry every
# field the pages read, of the type they read it as — every
# refund it lists and every sender each one pays included.
#
# Used by:
#   - tests/test_api_contract.py — every order the Flask app
#     answers
#   - tests/integration/test_live_smoke.py — the running
#     backend's orders
############################################################

def order_problems(order):
    problems = field_problems(order, ORDER_FIELDS, 'order')
    if problems:
        return problems

    for n, refund in enumerate(order['refunds']):
        found = field_problems(refund, REFUND_FIELDS, f'order.refunds[{n}]')
        problems += found
        if not found:
            for m, recipient in enumerate(refund['recipients']):
                problems += field_problems(recipient, RECIPIENT_FIELDS, f'order.refunds[{n}].recipients[{m}]')
    return problems








############################################################
# reserve_problems
############################################################
#
# What is wrong with a reserve answer: every field the
# reserves page reads, and on top of that EITHER a balance
# (its numbers — confirmed, unconfirmed, available — no
# error) OR the reason it has none (the error, every number
# null) — the page picks one of the two from the error field
# alone.
#
# Used by:
#   - tests/test_api_contract.py — the reserves the Flask app
#     answers
#   - tests/integration/test_live_smoke.py — the running
#     backend's reserves
############################################################

def reserve_problems(reserve):
    problems = field_problems(reserve, RESERVE_FIELDS, 'reserve')
    if problems:
        return problems

    balances = (reserve['confirmed'], reserve['unconfirmed'], reserve['available'])
    if reserve['error'] is None and None in balances:
        problems.append(f"reserve {reserve['network']} has no error but no balance either")
    if reserve['error'] is not None and balances != (None, None, None):
        problems.append(f"reserve {reserve['network']} has an error but still a balance")
    return problems








############################################################
# rates_problems
############################################################
#
# The rates answer: exactly the two directions under the keys
# the pages look up, each a positive number, the limits of
# both assets under their labels, a positive minimum below the
# maximum, the logo of both assets under their labels, and
# what the exchange can still pay out of each — no negative
# amount, or null while it is not known.
#
# Used by:
#   - tests/test_api_contract.py — the Flask app's rates
#   - tests/integration/test_live_smoke.py — the running
#     backend's rates
############################################################

def rates_problems(rates):
    if not isinstance(rates, dict):
        return [f'rates is not an object: {rates!r}']

    problems = []
    pairs = rates.get('pairs')
    if not isinstance(pairs, dict) or sorted(pairs) != sorted(PAIR_KEYS):
        problems.append(f'rates.pairs should hold exactly {list(PAIR_KEYS)}, got {pairs!r}')
    else:
        for key in PAIR_KEYS:
            if not (NUMBER[1](pairs[key]) and pairs[key] > 0):
                problems.append(f'rates.pairs[{key!r}] should be a positive number, got {pairs[key]!r}')

    limits = rates.get('limits')
    if not isinstance(limits, dict) or sorted(limits) != sorted(ASSETS):
        problems.append(f'rates.limits should hold exactly {list(ASSETS)}, got {limits!r}')
    else:
        for asset in ASSETS:
            low, high = (limits[asset] or {}).get('min'), (limits[asset] or {}).get('max')
            if not (NUMBER[1](low) and NUMBER[1](high) and 0 < low < high):
                problems.append(f'rates.limits[{asset!r}] should be 0 < min < max, got {limits[asset]!r}')

    icons = rates.get('icons')
    if not isinstance(icons, dict) or sorted(icons) != sorted(ASSETS):
        problems.append(f'rates.icons should hold exactly {list(ASSETS)}, got {icons!r}')
    else:
        for asset in ASSETS:
            if not ICON[1](icons[asset]):
                problems.append(f'rates.icons[{asset!r}] should be {ICON[0]}, got {icons[asset]!r}')

    capacity = rates.get('capacity')
    if not isinstance(capacity, dict) or sorted(capacity) != sorted(ASSETS):
        problems.append(f'rates.capacity should hold exactly {list(ASSETS)}, got {capacity!r}')
    else:
        for asset in ASSETS:
            if not (capacity[asset] is None or (NUMBER[1](capacity[asset]) and capacity[asset] >= 0)):
                problems.append(f'rates.capacity[{asset!r}] should be an amount or null, got {capacity[asset]!r}')
    return problems








############################################################
# error_problems
############################################################
#
# A failed answer: an object whose one field, error, is the
# sentence the page shows — when the error field is missing
# the page can only say which status came back.
#
# Used by:
#   - tests/test_api_contract.py — every failed answer
#   - tests/integration/test_live_smoke.py — the running
#     backend's 404
############################################################

def error_problems(body):
    if not (isinstance(body, dict) and set(body) == {'error'} and isinstance(body['error'], str) and body['error'].strip()):
        return [f'a failed answer should be {{"error": "<sentence>"}}, got {body!r}']
    return []
