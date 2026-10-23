############################################################
#  [*] Exchange configuration
#
#  Every environment knob of the exchange lives here and
#  nowhere else, read once at import time, so the rest of the
#  codebase imports this module and reads plain attributes.
#
#  Per-chain properties (Electrum server, confirmation
#  targets, names, explorer, ...) do NOT live here — they are
#  the operator's, in the mounted _CONFIG/coins.py, loaded and
#  validated by app/chains.py. This module only holds the
#  global knobs, and where that mounted folder is.
#
#  validate() should be called once on startup: it fails fast
#  with a clear message instead of letting a missing wallet
#  seed or a broken coins file crash deep inside the worker
#  on its first tick.
#
#  Used by:
#    - main.py        — validate() on startup, the log level
#                       and debug mode
#    - app/chains.py  — the mounted folder the coins file is
#                       read from
#    - app/service.py — the fee rate and the KNF → tLTC4 rate
#    - app/icons.py   — the mounted folder the coin logos
#                       live in
############################################################


import os








############################################################
# Pricing
############################################################
#
# The one rate the exchange prices with — KNF in tLTC4, the
# reverse pair its inverse — quoted when an order is created
# and paid at when its deposit confirms.
############################################################

# Reference price: how much tLTC4 one KNF is worth. The reverse pair is
# just 1 / rate.
RATE_KNF_TO_LTC = float(os.getenv('RATE_KNF_LTC', '0.12345678'))








############################################################
# Transactions
############################################################
#
# The fee rate of every transaction the exchange signs, on
# both chains. (Each chain's Electrum server is the
# operator's choice in _CONFIG/coins.py.)
############################################################

# Fee rate (sat/vbyte) used for payout and sweep transactions.
FEE_RATE_SATVB = int(os.getenv('BTC_FEE_RATE_SATVB', '10'))








############################################################
# App behaviour
############################################################
#
# How the Flask app itself runs: debug mode and the log
# level.
############################################################

# Flask debug mode; enabled in docker-compose for the classroom.
APP_DEBUG = os.getenv('APP_DEBUG', 'false').lower() == 'true'

# Root log level for the exchange.* loggers configured in main.py.
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()


# NOTE: two settings intentionally stay out of this module:
#   DB_PATH               — resolved at CALL time in app/database.py so
#                           tests can repoint the database per test case
#   EXCHANGE_PRIVATE_KEY  — read at wallet construction in app/wallet.py
#                           for the same reason; validate() below still
#                           checks it at startup








############################################################
# Mounted configuration
############################################################
#
# Where the operator's mounted configuration folder lives —
# coins.py, the chains the exchange trades, and the coin
# logos under icons/. An explicit CONFIG_DIR wins; otherwise
# the docker mount at /config (the compose line that mounts
# ./_CONFIG there), and failing that the repository's own
# _CONFIG, for runs straight from a checkout.
############################################################

# The repository's _CONFIG folder, two levels above this file
_REPO_CONFIG_DIR = os.path.abspath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '_CONFIG')
)

CONFIG_DIR = os.getenv('CONFIG_DIR') or ('/config' if os.path.isdir('/config') else _REPO_CONFIG_DIR)








############################################################
# validate
############################################################
#
# Called once from create_app() before anything else starts.
# Anything wrong here (missing seed, nonsense rate, a coins
# file that does not load or does not configure exactly the
# chains the exchange trades) dies immediately with a
# readable error instead of surfacing minutes later as a
# worker crash or an unpayable order. Importing app.chains is
# what loads and validates the coins file, entry by entry.
#
# (The app.chains and app.service imports are deliberately
# local — both import config, so module-level imports would
# be a cycle.)
#
# Used by:
#   - main.py — create_app()
############################################################

def validate() -> None:
    from .chains import CHAINS
    from .service import ASSET_TO_NETWORK

    seed = os.getenv('EXCHANGE_PRIVATE_KEY', '')
    if not seed:
        raise SystemExit('[CONFIG] EXCHANGE_PRIVATE_KEY environment variable is required (HD wallet seed)')

    hex_seed = seed.replace('0x', '')
    try:
        bytes.fromhex(hex_seed.ljust(64, '0')[:64])
    except ValueError:
        raise SystemExit('[CONFIG] EXCHANGE_PRIVATE_KEY must be a hex string')

    # The wallet pads a short seed with zeros up to 32 bytes, so a seed of a
    # few hex digits would make a wallet anyone could rebuild: anything below
    # 128 bits is refused.
    if len(hex_seed) < 32:
        raise SystemExit('[CONFIG] EXCHANGE_PRIVATE_KEY must be at least 32 hex characters (128 bits)')

    if RATE_KNF_TO_LTC <= 0:
        raise SystemExit(f'[CONFIG] RATE_KNF_LTC must be positive, got {RATE_KNF_TO_LTC}')

    if FEE_RATE_SATVB <= 0:
        raise SystemExit(f'[CONFIG] BTC_FEE_RATE_SATVB must be positive, got {FEE_RATE_SATVB}')

    # Every chain of the coins file is valid by now (app/chains.py stops
    # the start otherwise); the exchange trades exactly the chains its
    # asset table names, so the file must configure those and no other
    traded = sorted(set(ASSET_TO_NETWORK.values()))
    if sorted(CHAINS) != traded:
        raise SystemExit(f'[CONFIG] coins.py must configure exactly the chains the exchange trades, {traded} — '
                         f'it configures {sorted(CHAINS)}')
