############################################################
#  [*] Coins configuration — the operator-editable file
#
#  The chains the exchange trades, one entry each. This file
#  is MOUNTED into the backend container (./_CONFIG:/config)
#  and loaded at startup — editing it needs a backend restart
#  (docker restart knfexchange-backend), never an image
#  rebuild.
#
#  Everything here is validated on boot (app/chains.py) — a
#  misspelled key, an unknown coin or flavour, a malformed
#  Electrum endpoint or a missing chain kills the boot with a
#  precise error in the container logs.
#
#  Logos live next door in icons/<key>.svg (or .png / .webp),
#  where <key> is the entry's key in CHAIN_CONFIGS ('knf',
#  'ltc4'). Dropping a file there is enough — no restart
#  needed.
#
#  Used by:
#    - backend/app/chains.py — loaded at startup, validated,
#      then handed to the rest of the backend as CHAINS
############################################################








############################################################
# CHAIN_CONFIGS
############################################################
#
# The two chains of the KNF Coin <-> LTC Testnet pair, keyed
# by the network key the whole exchange knows them by — the
# key also names the chain's logo file. Exactly these two:
# the pair is fixed in the exchange's code, so an entry
# missing or added stops the boot. Each entry is sectioned:
#
#   (top level)  — identity: the ticker-style short name and
#                  the human-readable name the reserves page
#                  shows
#   'exchange'   — the OPERATOR's choices: which coin, which
#                  network flavour, how many confirmations a
#                  deposit needs before it is exchanged and
#                  paid out (payouts confirm as deep), and the
#                  ElectrumX endpoint (host:port, TLS)
#   'explorer'   — where the reserves page links the chain's
#                  addresses; optional
#
# 'coin' names an entry of the backend's coin registry
# (app/coins.py): 'knfcoin' (mainnet) and 'litecoin'
# (testnet). Everything protocol-precise — the bech32 prefix
# of the addresses — lives in that registry, not here. An
# unknown coin or flavour fails the boot naming the known
# options.
############################################################

CHAIN_CONFIGS = {
    'knf': {
        'short_name': 'KNF',
        'full_name': 'KNF Coin',
        'exchange': {
            'coin': 'knfcoin',
            'network': 'mainnet',
            'confirm_target': 2,
            'electrum_server': '158.129.172.247:49002',
        },
        'explorer': {
            # The KNF explorer this stack serves itself, behind the same endpoint
            'block_explorer': '/explorer',
        },
    },
    'ltc4': {
        'short_name': 'tLTC4',
        'full_name': 'Litecoin Testnet4',
        'exchange': {
            'coin': 'litecoin',
            'network': 'testnet',
            'confirm_target': 2,
            'electrum_server': '158.129.172.247:50002',
        },
        'explorer': {
            'block_explorer': 'https://litecoinspace.org/testnet',
        },
    },
}
