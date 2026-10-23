############################################################
#  [*] Coin registry — protocol facts, not operator choices
#
#  Every coin's PROTOCOL CONSTANTS live here: the bech32
#  prefix of its addresses on each network flavour. These are
#  facts about the coin — a Litecoin testnet address starts
#  with 'tltc' whether the operator likes it or not — so the
#  operator's config (_CONFIG/coins.py) never sees them. It
#  names a coin and a network flavour ('litecoin' +
#  'testnet'); everything precise resolves from here at
#  startup, and a typo there can never yield addresses no
#  wallet recognizes.
#
#  Only valueless coins are listed: Litecoin's mainnet is
#  deliberately absent, so no configuration can make the
#  exchange pay out real money. Every coin here signs by
#  Litecoin's key rules on its flavour (the wallet picks
#  bitcoinlib's litecoin or litecoin_testnet by the network
#  flavour), so a coin that does not would need the wallet
#  taught first.
#
#  Used by:
#    - app/chains.py — the boot validation of each chain's
#      coin and network flavour
############################################################


# Operator-facing coin name -> network flavour -> its facts
COINS = {
    'knfcoin': {
        # The faculty's own Litecoin-derived chain; mainnet only —
        # there is no public KNF testnet
        'mainnet': {'bech32_hrp': 'knf'},
    },
    'litecoin': {
        'testnet': {'bech32_hrp': 'tltc'},
    },
}








############################################################
# coin_params
############################################################
#
# The facts of one coin on one network flavour. Raises
# ValueError naming the known options — the boot validation
# surfaces that sentence verbatim.
#
# Used by:
#   - app/chains.py — chain_definitions, once per chain
############################################################

def coin_params(coin, network) -> dict:
    flavours = COINS.get(coin)
    if flavours is None:
        raise ValueError(f"unknown coin '{coin}' — known coins: {sorted(COINS)}")

    params = flavours.get(network)
    if params is None:
        raise ValueError(f"coin '{coin}' has no '{network}' flavour — available: {sorted(flavours)}")

    return dict(params)
