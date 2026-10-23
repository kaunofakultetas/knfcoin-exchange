############################################################
#  [*] Chain registry
#
#  Central lookup of every chain this exchange can trade.
#  Instead of scattering per-chain knowledge (Electrum server,
#  bech32 prefix, confirmation targets) across the codebase,
#  each chain is one frozen ChainDefinition and the rest of
#  the exchange only ever asks the registry.
#
#  The chains are the operator's: they come from coins.py in
#  the mounted configuration folder (CONFIG_DIR — see
#  app/config.py), read once at import and validated entry by
#  entry. The file holds only choices — names, coin, network
#  flavour, confirmations, Electrum endpoint, explorer — while
#  the protocol facts of each coin come from app/coins.py.
#  Any fault (a missing file, a misspelled key, an unknown
#  coin, a malformed endpoint) stops the start with one
#  sentence naming the file, the chain and the fault.
#
#  Changing a chain — another Electrum server, explorer or
#  confirmation target — is an edit of _CONFIG/coins.py and a
#  backend restart. A new chain needs code as well: its coin
#  in app/coins.py, its display name in ASSET_TO_NETWORK and a
#  price in pair_rate (app/service.py) — the exchange trades
#  exactly the pair it prices, and config.validate() checks
#  the file configures exactly its chains.
#
#  Used by:
#    - main.py        — passed into ExchangeService
#    - app/config.py  — validate()
#    - app/wallet.py  — one wallet per ChainDefinition
#    - app/service.py — confirmation targets, display names
############################################################


import os
import re
import importlib.util
from dataclasses import dataclass
from typing import Optional

from . import config
from .coins import coin_params


# A chain key becomes a URL segment and a logo file name —
# letters, digits, '-' and '_' only
KEY_PATTERN = re.compile(r'^[A-Za-z0-9_-]+$')

# An ElectrumX endpoint: host:port, the port checked for its
# range separately
ENDPOINT_PATTERN = re.compile(r'^[\w.\-]+:(\d+)$')

# A block explorer: an http(s) URL, or a path on this site
EXPLORER_PATTERN = re.compile(r'^(https?://\S+|/\S*)$')

# The keys each part of an entry takes: the required ones,
# then the optional ones — anything else is a typo
ENTRY_KEYS = ({'short_name', 'full_name', 'exchange'}, {'explorer'})
EXCHANGE_KEYS = ({'coin', 'network', 'confirm_target', 'electrum_server'}, set())
EXPLORER_KEYS = ({'block_explorer'}, set())








############################################################
# ChainDefinition
############################################################
#
# Everything the wallet and service layers need to know about
# one chain, built from its validated entry. Frozen so a
# definition can never drift at runtime — chains are
# configuration, not state.
#
# Used by:
#   - chain_definitions (below) — one definition per chain
#   - app/service.py — ExchangeService keeps them by network
#     key; app/wallet.py — each ExchangeWallet is built on one
############################################################

@dataclass(frozen=True)
class ChainDefinition:

    # Ticker-style short name, e.g. "KNF" (logs, reserves UI)
    short_name: str

    # Human-readable name, e.g. "Litecoin Testnet4"
    full_name: str

    # "mainnet" or "testnet" — selects bitcoinlib's key rules
    # (KNF is a Litecoin fork, so Litecoin's rules fit both)
    network: str

    # bech32 prefix of native-segwit addresses on this chain,
    # e.g. "knf" for knf1q... / "tltc" for tltc1q...
    bech32_hrp: str

    # ElectrumX endpoint, "host:port" (TLS)
    electrum_server: str

    # Where the frontend links to for this chain's addresses,
    # or None for a chain without an explorer
    block_explorer: Optional[str]

    # On-chain confirmations required before a deposit is
    # exchanged and paid out
    confirm_target: int








############################################################
# _check_keys
############################################################
#
# One part of an entry must be a dict holding every required
# key and nothing beyond the optional ones — what turns a
# misspelled key from a silent fallback into a boot failure
# naming it.
#
# Used by:
#   - _definition (below)
############################################################

def _check_keys(part, required, optional, where):
    if not isinstance(part, dict):
        raise ValueError(f'{where} must be a dict, got {part!r}')

    unknown = sorted(str(key) for key in set(part) - required - optional)
    if unknown:
        raise ValueError(f"unknown key {', '.join(map(repr, unknown))} in {where}")

    missing = sorted(required - set(part))
    if missing:
        raise ValueError(f"{where} lacks {', '.join(map(repr, missing))}")








############################################################
# _definition
############################################################
#
# One validated entry as its ChainDefinition: the names
# non-empty, the coin and flavour known to the registry (whose
# bech32 prefix the chain then uses), the confirmation target
# a whole number of at least one, the Electrum endpoint
# host:port with a real TCP port, and the explorer — when
# there is one — a URL or a path on this site. Raises
# ValueError with the fault in one sentence.
#
# Used by:
#   - chain_definitions (below)
############################################################

def _definition(entry) -> ChainDefinition:
    # STEP 1: the shape — every section with exactly its keys
    # =======================================================
    _check_keys(entry, *ENTRY_KEYS, 'the entry')
    exchange = entry['exchange']
    _check_keys(exchange, *EXCHANGE_KEYS, "the 'exchange' section")
    explorer = entry.get('explorer')
    if explorer is not None:
        _check_keys(explorer, *EXPLORER_KEYS, "the 'explorer' section")


    # STEP 2: the identity
    # ====================
    for name in ('short_name', 'full_name'):
        if not isinstance(entry[name], str) or not entry[name].strip():
            raise ValueError(f'{name} must be a non-empty text, got {entry[name]!r}')


    # STEP 3: the operator's choices — the coin and flavour
    # resolved in the registry, the confirmations, the endpoint
    # =========================================================
    params = coin_params(exchange['coin'], exchange['network'])

    target = exchange['confirm_target']
    if isinstance(target, bool) or not isinstance(target, int) or target < 1:
        raise ValueError(f'confirm_target must be a whole number of at least 1, got {target!r}')

    endpoint = exchange['electrum_server']
    match = ENDPOINT_PATTERN.match(endpoint) if isinstance(endpoint, str) else None
    if not match:
        raise ValueError(f'electrum_server must be host:port, got {endpoint!r}')
    if not 1 <= int(match.group(1)) <= 65535:
        raise ValueError(f'electrum_server port {match.group(1)} is not a valid TCP port (1-65535)')


    # STEP 4: the explorer, when there is one
    # =======================================
    block_explorer = None
    if explorer is not None:
        block_explorer = explorer['block_explorer']
        if not (isinstance(block_explorer, str) and EXPLORER_PATTERN.match(block_explorer)):
            raise ValueError(f'block_explorer must be an http(s) URL or a path on this site, got {block_explorer!r}')

    return ChainDefinition(
        short_name=entry['short_name'],
        full_name=entry['full_name'],
        network=exchange['network'],
        bech32_hrp=params['bech32_hrp'],
        electrum_server=endpoint,
        block_explorer=block_explorer,
        confirm_target=target,
    )








############################################################
# chain_definitions
############################################################
#
# The whole CHAIN_CONFIGS map as ChainDefinitions by network
# key, in the file's order — the order the reserves page
# lists the chains in. A key that is not URL-safe or an entry
# that does not validate raises ValueError naming the chain.
#
# Used by:
#   - load_chains (below)
############################################################

def chain_definitions(configs) -> dict:
    if not isinstance(configs, dict) or not configs:
        raise ValueError(f'CHAIN_CONFIGS must be a non-empty dict of chains, got {configs!r}')

    chains = {}
    for key, entry in configs.items():
        if not isinstance(key, str) or not KEY_PATTERN.match(key):
            raise ValueError(f"chain key {key!r} is not URL-safe — use letters, digits, '-' and '_' only")
        try:
            chains[key] = _definition(entry)
        except ValueError as e:
            raise ValueError(f"chain '{key}' is misconfigured: {e}") from None

    return chains








############################################################
# load_chains
############################################################
#
# Reads the operator's coins file and hands back its chains,
# validated. Whatever goes wrong — no file (the folder not
# mounted), a file Python cannot run, no CHAIN_CONFIGS in it,
# a chain that does not validate — stops the start with a
# "[CONFIG]" sentence naming the file.
#
# Used by:
#   - CHAINS (below), at import
############################################################

def load_chains(path) -> dict:
    # STEP 1: the file, where the mount puts it
    # =========================================
    if not os.path.isfile(path):
        raise SystemExit(f'[CONFIG] no coins file at {path} — mount the _CONFIG folder at /config (./_CONFIG:/config:ro)')


    # STEP 2: run it, as the plain Python it is
    # =========================================
    try:
        spec = importlib.util.spec_from_file_location('coins_config', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception as e:
        raise SystemExit(f'[CONFIG] {path} could not be loaded: {e}')

    if not hasattr(module, 'CHAIN_CONFIGS'):
        raise SystemExit(f'[CONFIG] {path} defines no CHAIN_CONFIGS')


    # STEP 3: every chain validated
    # =============================
    try:
        return chain_definitions(module.CHAIN_CONFIGS)
    except ValueError as e:
        raise SystemExit(f'[CONFIG] {path}: {e}')








############################################################
# CHAINS
############################################################
#
# The operator's chains, loaded once when this module is
# first imported — which config.validate() does before
# anything else starts.
#
# Used by:
#   - main.py — create_app hands them to ExchangeService
#   - app/config.py — validate() checks they are exactly the
#     chains the exchange trades
############################################################

CHAINS = load_chains(os.path.join(config.CONFIG_DIR, 'coins.py'))
