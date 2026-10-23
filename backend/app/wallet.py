############################################################
#  [*] Exchange wallet
#
#  UTXO wallet for one chain (KNF or tLTC4). Three jobs:
#
#    - derive a fresh deposit address per order (and the
#      reserve/payout address) from a single HD seed
#    - watch addresses over Electrum (history, balance,
#      confirmations) — what each query asks and how its
#      answer is read; the connection itself is the chain's
#      ElectrumClient (app/electrum_client.py)
#    - build, sign and broadcast payout transactions from
#      the reserve address, sweeps of finished deposits back
#      into it, and refunds of the coins an order could not
#      exchange to the addresses they came from
#
#  It works for KNF Coin even though bitcoinlib has no "knf"
#  network: addresses are handled manually with bech32, and
#  bitcoinlib is used only for key math and transaction
#  signing (KNF is a Litecoin fork, so Litecoin's rules fit).
#
#  Used by:
#    - app/service.py — one instance per chain, created lazily
############################################################


import os
import hashlib
from dataclasses import dataclass

import bech32
from bitcoinlib.keys import HDKey
from bitcoinlib.transactions import Transaction, Output, Input

from .electrum_client import ElectrumClient


# Satoshis per coin (both chains use 8 decimals). Everything below the API
# layer counts in satoshis; division by COIN happens only for display/API.
COIN = 100_000_000

# Litecoin/KNF dust limit in satoshis - outputs smaller than this are
# rejected by the network, so change below it is dropped into the fee.
DUST_LIMIT_SAT = 546

# Fixed HD child index used as the exchange's reserve (payout) address on
# each chain. Deposit addresses use indexes 1, 2, 3, ... so they never
# collide with the reserve.
RESERVE_INDEX = 0

# The constant a bech32m checksum (BIP-350, taproot addresses) ends on;
# the bech32 package only knows bech32's
BECH32M_CONST = 0x2bc830a3








############################################################
# ReserveShortfall
############################################################
#
# Raised when the reserve holds too little to pay a payout —
# nothing at all, or less than the amount and the fee it
# costs. Unlike an Electrum outage it is an answer, not a
# failure to get one: the worker sends the order's coins back
# instead of trying again.
#
# Used by:
#   - ExchangeWallet.build_payout_tx (below) — raises it
#   - app/worker.py — _send_payout, which refunds the order
############################################################

class ReserveShortfall(ValueError):
    pass








############################################################
# spend_fee_sat
############################################################
#
# The fee of a transaction spending input_count p2wpkh coins
# into output_count outputs at the given rate: the size is
# estimated at ~68 vbytes an input, ~31 an output and ~11
# fixed — close enough for the standard scripts the exchange
# pays to, and slightly under for the bigger ones.
#
# Used by:
#   - refund_plan, ExchangeWallet.build_payout_tx,
#     ExchangeWallet.build_sweep_tx (below)
#   - app/service.py — the fee a new order's payout will cost
#     the reserve
############################################################

def spend_fee_sat(input_count: int, output_count: int, fee_rate_sat_vb: int) -> int:
    return ((input_count * 68) + (output_count * 31) + 11) * fee_rate_sat_vb








############################################################
# format_coins
############################################################
#
# An amount of whole coins as the sentences the exchange
# writes show it: at most 8 decimals, no trailing zeros.
#
# Used by:
#   - app/service.py — the refusal of an order the reserve
#     cannot cover
#   - app/worker.py — why an order's coins were sent back
############################################################

def format_coins(amount: float) -> str:
    return f'{amount:.8f}'.rstrip('0').rstrip('.')








############################################################
# refund_plan
############################################################
#
# How a set of coins goes back to the addresses that sent
# them: grouped by the output script each one is refunded to
# (its refund_to), each group paying the fee of its own coins
# and its own output — the first one the fixed part of the
# transaction as well. A group left with no more than dust
# after its share is dropped, its coins staying where they
# are, and the shares are worked out again for the rest.
# Answers (refund_to, amount in satoshis, its coins) per
# group kept, in the order the coins came in — empty when
# nothing is worth sending back.
#
# Used by:
#   - ExchangeWallet.build_refund_tx (below)
#   - tests/fakes.py — the test wallets refund the same way
############################################################

def refund_plan(coins: list, fee_rate_sat_vb: int) -> list:
    groups = {}
    for coin in coins:
        groups.setdefault(coin['refund_to'], []).append(coin)

    plan = list(groups.items())
    while plan:
        amounts = [sum(int(coin['value']) for coin in group) - (len(group) * 68 + 31) * fee_rate_sat_vb
                   for _refund_to, group in plan]
        amounts[0] -= 11 * fee_rate_sat_vb

        kept = [(refund_to, amount, group) for (refund_to, group), amount in zip(plan, amounts) if amount > DUST_LIMIT_SAT]
        if len(kept) == len(plan):
            return kept
        plan = [(refund_to, group) for refund_to, _amount, group in kept]

    return []








############################################################
# _bech32m_address
############################################################
#
# A witness version 1 (taproot) program as its bech32m
# address — bech32's encoding with BIP-350's checksum
# constant, which the bech32 package (1.2.0) predates.
#
# Used by:
#   - ExchangeWallet.address_of (below)
############################################################

def _bech32m_address(hrp: str, witver: int, program: bytes) -> str:
    data = [witver] + bech32.convertbits(list(program), 8, 5)
    polymod = bech32.bech32_polymod(bech32.bech32_hrp_expand(hrp) + data + [0] * 6) ^ BECH32M_CONST
    checksum = [(polymod >> 5 * (5 - i)) & 31 for i in range(6)]
    return hrp + '1' + ''.join(bech32.CHARSET[d] for d in data + checksum)








############################################################
# DerivedKey
############################################################
#
# Bundles one HD child key with everything the rest of the
# code needs about it: its bech32 address, the Electrum
# scripthash used to watch it, and the index it was derived
# at (persisted on the order so we can re-derive later).
#
# Used by:
#   - ExchangeWallet.derive (below)
############################################################

@dataclass
class DerivedKey:
    index:      int
    key:        HDKey
    address:    str
    scripthash: str








############################################################
# ExchangeWallet
############################################################
#
# Single-chain wallet, configured by one ChainDefinition from
# app/chains.py: which Electrum server to talk to, the bech32
# prefix its addresses use, and whether the chain is mainnet
# or testnet (for key encoding).
#
# Used by:
#   - app/service.py — wallet_for builds one per chain
############################################################

class ExchangeWallet:






    ############################################################
    # __init__
    ############################################################
    #
    # Builds the chain's Electrum client (it connects on its
    # first request), the HD master key from the seed, and
    # derives the reserve address. Raises when the seed is
    # missing — nothing is contacted yet.
    #
    # Used by:
    #   - app/service.py — wallet_for, on a chain's first use
    ############################################################

    def __init__(self, chain):
        self.chain = chain
        self.hrp = chain.bech32_hrp

        # The chain's Electrum server, behind one long-lived connection
        self.electrum = ElectrumClient(chain.electrum_server)

        # bitcoinlib network name, used purely for key handling and signing.
        # KNF is a Litecoin mainnet fork, so it reuses Litecoin's rules; the
        # differing address prefix is applied by us, not by bitcoinlib.
        self.bl_network = 'litecoin' if chain.network == 'mainnet' else 'litecoin_testnet'

        # EXCHANGE_PRIVATE_KEY is treated as an HD seed. Every deposit
        # address and the reserve address are children of this one master
        # key, so the whole exchange is recoverable from a single secret.
        self.master = HDKey.from_seed(self._seed_bytes(), network=self.bl_network)

        # Pre-derive the reserve address (payout source for this chain).
        self.reserve = self.derive(RESERVE_INDEX)






    ############################################################
    # _seed_bytes
    ############################################################
    #
    # The HD seed from EXCHANGE_PRIVATE_KEY as exactly 32 bytes.
    # A shorter hex string is padded with zeros — which is why
    # config.validate() refuses one below 128 bits at startup.
    #
    # Used by:
    #   - __init__ (above)
    ############################################################

    @staticmethod
    def _seed_bytes() -> bytes:
        raw = os.getenv('EXCHANGE_PRIVATE_KEY')
        if not raw:
            raise ValueError('EXCHANGE_PRIVATE_KEY environment variable not set')

        # Accept an optional 0x prefix and normalise to exactly 64 hex chars
        # (32 bytes) so from_seed always gets a well-formed seed.
        return bytes.fromhex(raw.replace('0x', '').ljust(64, '0')[:64])






    ############################################################
    # derive
    ############################################################
    #
    # The key at one HD child index: deposit addresses are
    # plain BIP32 children at m/0/<index>, each a native SegWit
    # v0 pay-to-witness-public-key-hash (p2wpkh) address,
    # encoded with this chain's bech32 prefix (knf / tltc).
    #
    # Used by:
    #   - __init__ (above) — the reserve, index 0
    #   - app/service.py — create_order, a deposit address per
    #     order
    #   - app/worker.py — _sweep_deposit re-derives a deposit's
    #     key to sweep it
    ############################################################

    def derive(self, index: int) -> DerivedKey:
        child = self.master.subkey_for_path(f'0/{index}')

        pubkey_hash = self._hash160(child.public_byte)
        address = bech32.encode(self.hrp, 0, list(pubkey_hash))
        scripthash = self._address_to_scripthash(address)

        return DerivedKey(index=index, key=child, address=address, scripthash=scripthash)






    ############################################################
    # _hash160
    ############################################################
    #
    # RIPEMD160 of the SHA256 of the data — the public-key hash
    # a p2wpkh address commits to.
    #
    # Used by:
    #   - derive (above)
    ############################################################

    @staticmethod
    def _hash160(data: bytes) -> bytes:
        sha = hashlib.sha256(data).digest()
        return hashlib.new('ripemd160', sha).digest()






    ############################################################
    # is_valid_address
    ############################################################
    #
    # Whether an address can receive on THIS chain: bech32 with
    # our prefix, witness v0, 20-byte program (native SegWit
    # p2wpkh) — the only kind the wallet can pay.
    #
    # Used by:
    #   - _address_to_script (below)
    #   - app/service.py — create_order, the destination
    ############################################################

    def is_valid_address(self, address: str) -> bool:
        witver, program = bech32.decode(self.hrp, address)
        return witver == 0 and program is not None and len(program) == 20






    ############################################################
    # _address_to_script
    ############################################################
    #
    # The scriptPubKey of a p2wpkh address: OP_0 (0x00), a push
    # of 20 bytes (0x14) and the witness program. An address
    # this chain cannot pay raises before any script is built.
    #
    # Used by:
    #   - _address_to_scripthash, build_payout_tx,
    #     build_sweep_tx (below)
    ############################################################

    def _address_to_script(self, address: str) -> bytes:
        if not self.is_valid_address(address):
            raise ValueError(f'Invalid {self.hrp} address: {address}')

        _witver, program = bech32.decode(self.hrp, address)
        return b'\x00\x14' + bytes(program)






    ############################################################
    # _address_to_scripthash
    ############################################################
    #
    # Electrum identifies an address by the SHA256 of its
    # scriptPubKey, byte-reversed and hex-encoded.
    #
    # Used by:
    #   - derive (above), payout_confirmations (below)
    ############################################################

    def _address_to_scripthash(self, address: str) -> str:
        script = self._address_to_script(address)
        return hashlib.sha256(script).digest()[::-1].hex()






    ############################################################
    # get_tip_height
    ############################################################
    #
    # Current best block height, used to turn a tx's block
    # height into a confirmation count. An ElectrumX that is
    # still syncing answers None instead of a header, which is
    # reported as height 0.
    #
    # Used by:
    #   - payout_confirmations (below)
    #   - app/worker.py — _deposit_coins
    #   - app/service.py — reserves_snapshot, to tell a syncing
    #     server from an empty wallet
    ############################################################

    def get_tip_height(self) -> int:
        header = self.electrum.request('blockchain.headers.subscribe', []) or {}
        return int(header.get('height', 0))






    ############################################################
    # get_history
    ############################################################
    #
    # Every transaction touching an address: tx_hash and
    # height pairs, height 0 or -1 meaning still in the
    # mempool. An address never used has none.
    #
    # Used by:
    #   - payout_confirmations (below)
    #   - app/worker.py — _check_deposit, _check_confirmations,
    #     _sweep_deposit
    ############################################################

    def get_history(self, scripthash: str) -> list:
        return self.electrum.request('blockchain.scripthash.get_history', [scripthash]) or []






    ############################################################
    # get_unspent
    ############################################################
    #
    # The coins on an address — tx_hash, tx_pos, height and
    # value in satoshis each — mempool ones included.
    #
    # ElectrumX can transiently report the same outpoint TWICE
    # while a transaction is moving from the mempool into a
    # fresh block (one entry from each view). Summing that raw
    # list double-counts the deposit, so only one entry per
    # (tx_hash, tx_pos) is kept — the confirmed one (height >
    # 0) when both are present.
    #
    # Used by:
    #   - get_received_sat, build_payout_tx, build_sweep_tx
    #     (below)
    #   - app/worker.py — _deposit_coins, _deposit_still_backs,
    #     _sweep_deposit
    ############################################################

    def get_unspent(self, scripthash: str) -> list:
        utxos = self.electrum.request('blockchain.scripthash.listunspent', [scripthash]) or []

        unique = {}
        for utxo in utxos:
            outpoint = (utxo['tx_hash'], utxo['tx_pos'])
            if outpoint not in unique or int(utxo.get('height', 0)) > 0:
                unique[outpoint] = utxo

        return list(unique.values())






    ############################################################
    # get_balance_sat
    ############################################################
    #
    # An address's confirmed and unconfirmed balance in
    # satoshis, straight from Electrum. Used for the reserve
    # wallet, which spends from itself, so unlike
    # get_received_sat below this must be a real balance query
    # (an unconfirmed spend shows as a negative amount).
    #
    # Used by:
    #   - app/service.py — reserves_snapshot
    ############################################################

    def get_balance_sat(self, scripthash: str) -> dict:
        balance = self.electrum.request('blockchain.scripthash.get_balance', [scripthash]) or {}
        return {
            'confirmed':   int(balance.get('confirmed', 0)),
            'unconfirmed': int(balance.get('unconfirmed', 0)),
        }






    ############################################################
    # reserve_balance_sat
    ############################################################
    #
    # What the reserve can spend right now, in satoshis: its
    # confirmed balance and the unconfirmed one together, since
    # a payout spends unconfirmed coins once the confirmed ones
    # fall short. Only a server with a chain tip is asked — a
    # syncing one answers 0 for every address, which would read
    # as an empty reserve — and an outage raises rather than
    # reading as one.
    #
    # Used by:
    #   - app/service.py — what a new order's payout can be
    #     covered with
    ############################################################

    def reserve_balance_sat(self) -> int:
        if self.get_tip_height() <= 0:
            raise RuntimeError('Electrum server is still syncing (no chain tip yet)')

        balance = self.get_balance_sat(self.reserve.scripthash)
        return balance['confirmed'] + balance['unconfirmed']






    ############################################################
    # get_received_sat
    ############################################################
    #
    # Total still sitting on the address, in satoshis. Deposits
    # are never spent from their own address while the order
    # runs (payouts come from the reserve), so the sum of
    # unspent outputs equals what the student has deposited so
    # far — mempool coins included.
    #
    # Used by:
    #   - app/worker.py — _check_deposit, _revive_late_deposits
    ############################################################

    def get_received_sat(self, scripthash: str) -> int:
        return sum(int(u['value']) for u in self.get_unspent(scripthash))






    ############################################################
    # get_transaction
    ############################################################
    #
    # A transaction's raw hex, as the chain's Electrum server
    # hands it out. The exchange only asks about transactions
    # the chain holds — the deposits on its own addresses and
    # the ones they spend — so a server that does not hand one
    # out is in trouble, not answering: an outage, or a node
    # that keeps no transaction index (it refuses every
    # confirmed transaction, and the ones its index has not
    # reached while it is being built). Either way this raises,
    # in the server's own words, for the caller to try again.
    #
    # Used by:
    #   - sender_of (below)
    ############################################################

    def get_transaction(self, txid: str):
        return self.electrum.request('blockchain.transaction.get', [txid])






    ############################################################
    # sender_of
    ############################################################
    #
    # Where a refund of a deposit transaction's coins goes: the
    # output script that paid for its first input — the
    # student's own address, whatever its type. None when there
    # is none to find, for good: a coinbase, a transaction that
    # cannot be read here (bitcoinlib does not parse every
    # format, MWEB ones among them), a first input spending an
    # output that does not exist. A server that does not hand
    # out either transaction raises (see get_transaction) —
    # the sender is not missing then, only not found yet. Two
    # lookups: the deposit transaction, then the one whose
    # output its first input spends.
    #
    # Used by:
    #   - app/worker.py — the senders of the coins an order
    #     sends back
    ############################################################

    def sender_of(self, tx_hash: str):
        # STEP 1: the deposit transaction and its first input
        # ===================================================
        deposit = self._parsed(self.get_transaction(tx_hash))
        if deposit is None or deposit.coinbase or not deposit.inputs:
            return None
        first = deposit.inputs[0]


        # STEP 2: the output that input spent — its script is
        # where the coins came from
        # ===================================================
        funding = self._parsed(self.get_transaction(first.prev_txid.hex()))
        if funding is None or first.output_n_int >= len(funding.outputs):
            return None
        return funding.outputs[first.output_n_int].lock_script






    ############################################################
    # _parsed
    ############################################################
    #
    # A raw transaction as bitcoinlib reads it, or None for no
    # transaction or one it cannot read.
    #
    # Used by:
    #   - sender_of (above)
    ############################################################

    def _parsed(self, raw_hex):
        if not raw_hex:
            return None
        try:
            return Transaction.parse_hex(raw_hex, network=self.bl_network)
        except Exception:
            return None






    ############################################################
    # address_of
    ############################################################
    #
    # An output script as the address a student would read, in
    # this chain's prefix: bech32 for a SegWit v0 key or script
    # hash, bech32m for a taproot key. None for any other kind
    # (a legacy address, whose base58 prefixes the coin registry
    # does not hold) — a refund still pays to the script itself.
    #
    # Used by:
    #   - app/worker.py — the addresses a refund names
    ############################################################

    def address_of(self, script: bytes):
        if script[:2] in (b'\x00\x14', b'\x00\x20') and len(script) == 2 + script[1]:
            return bech32.encode(self.hrp, 0, list(script[2:]))
        if script[:2] == b'\x51\x20' and len(script) == 34:
            return _bech32m_address(self.hrp, 1, script[2:])
        return None






    ############################################################
    # confirmations
    ############################################################
    #
    # How deep a transaction touching an address lies: None
    # when that address's history - chain and mempool alike -
    # does not hold it (it never got out, or a reorganisation
    # lost it), 0 while it waits in the mempool. Every Electrum
    # server indexes histories by address, so this needs
    # nothing a server may lack.
    #
    # Used by:
    #   - payout_confirmations (below)
    #   - app/worker.py — a refund, followed through the
    #     history of the deposit address it spends from
    ############################################################

    def confirmations(self, txid: str, scripthash: str):
        heights = {entry['tx_hash']: int(entry['height']) for entry in self.get_history(scripthash)}
        if txid not in heights:
            return None

        height = heights[txid]
        return max(0, self.get_tip_height() - height + 1) if height > 0 else 0






    ############################################################
    # payout_confirmations
    ############################################################
    #
    # How deep a payout to `address` lies, read from the
    # history of the address it pays (see confirmations).
    #
    # Used by:
    #   - app/worker.py — _finish_pending_payout
    ############################################################

    def payout_confirmations(self, txid: str, address: str):
        return self.confirmations(txid, self._address_to_scripthash(address))






    ############################################################
    # build_payout_tx
    ############################################################
    #
    # Builds and signs a payout from this chain's reserve
    # address (HD index 0) and returns its txid and raw hex —
    # WITHOUT broadcasting it. Once an order finishes, its
    # deposited coins are swept from the per-order address into
    # the reserve (see build_sweep_tx), so the exchange refills
    # itself and the reserve only needs occasional out-of-band
    # top-ups. An empty or short reserve raises
    # ReserveShortfall with the shortfall in coins, on which the
    # worker sends the order's coins back.
    #
    # Building and broadcasting are deliberately SEPARATE
    # steps: the worker persists the signed transaction (and
    # its txid, computed locally) before broadcasting, so that
    # a crash at any point can only ever lead to the same
    # transaction being rebroadcast — never to a second payout.
    #
    # Used by:
    #   - app/worker.py — _send_payout
    ############################################################

    def build_payout_tx(self, to_address: str, amount_sat: int, fee_rate_sat_vb: int = 10):
        # STEP 1: the destination must be a valid address on THIS
        # chain before anything is spent
        # =======================================================
        destination_script = self._address_to_script(to_address)


        # STEP 2: the reserve's coins, confirmed ones first: an
        # unconfirmed one (a sweep or a top-up still in the
        # mempool) can vanish in a reorganisation and take the
        # payout built on it along, so it is only spent when the
        # confirmed coins cannot cover the payout (a stable sort
        # keeps the server's order within each group)
        # ======================================================
        utxos = self.get_unspent(self.reserve.scripthash)
        if not utxos:
            raise ReserveShortfall('Reserve address has no funds to pay out')

        utxos = sorted(utxos, key=lambda utxo: int(utxo.get('height', 0)) <= 0)


        # STEP 3: gather inputs until they cover the amount AND the
        # fee they cost — every input added makes the transaction,
        # and its fee, larger
        # =========================================================
        # Two outputs: the payout and the change
        fee_for = lambda input_count: spend_fee_sat(input_count, 2, fee_rate_sat_vb)

        inputs = []
        total_input = 0
        for utxo in utxos:
            inputs.append(Input(
                prev_txid=utxo['tx_hash'],
                output_n=utxo['tx_pos'],
                keys=self.reserve.key,
                value=int(utxo['value']),
                witness_type='segwit',
                network=self.bl_network,
            ))
            total_input += int(utxo['value'])
            if total_input >= amount_sat + fee_for(len(inputs)):
                break

        fee = fee_for(len(inputs))

        if total_input < amount_sat + fee:
            raise ReserveShortfall(f'Insufficient reserve funds: have {format_coins(total_input / COIN)} {self.chain.short_name}, '
                                   f'need {format_coins((amount_sat + fee) / COIN)} {self.chain.short_name}')


        # STEP 4: the outputs, built from explicit lock scripts —
        # what lets us pay a KNF (knf1...) address bitcoinlib
        # itself cannot parse — with the change back to the
        # reserve unless it is dust
        # =======================================================
        outputs = [Output(amount_sat, lock_script=destination_script, network=self.bl_network)]

        change = total_input - amount_sat - fee
        if change > DUST_LIMIT_SAT:
            change_script = self._address_to_script(self.reserve.address)
            outputs.append(Output(change, lock_script=change_script, network=self.bl_network))


        # STEP 5: sign, and compute the txid locally (by re-parsing
        # the serialized tx) so the worker can persist it before
        # the network ever sees the payout
        # =========================================================
        tx = Transaction(inputs=inputs, outputs=outputs, network=self.bl_network, witness_type='segwit')
        tx.sign(self.reserve.key)
        raw_hex = tx.raw_hex()

        txid = Transaction.parse_hex(raw_hex).txid
        return txid, raw_hex






    ############################################################
    # broadcast
    ############################################################
    #
    # Hands a signed transaction to the network and answers the
    # server's txid. Broadcasting the same raw transaction twice
    # is harmless: the txid is identical, so the network either
    # accepts it once or reports it as already known.
    #
    # Used by:
    #   - app/worker.py — _send_payout, _finish_pending_payout,
    #     _sweep_deposit
    ############################################################

    def broadcast(self, raw_hex: str) -> str:
        return self.electrum.request('blockchain.transaction.broadcast', [raw_hex])






    ############################################################
    # build_sweep_tx
    ############################################################
    #
    # Signs a transaction sweeping a deposit address's coins
    # into the reserve, so future payouts can spend what the
    # student deposited, and returns its txid, raw hex and the
    # amount the reserve receives — or None when there is
    # nothing to sweep or too little to be worth a transaction
    # (no more than dust after the fee). By default every coin
    # on the address goes; given `coins`, only those — the ones
    # an order's payout paid for, so a coin that arrived later
    # stays to be sent back. Every coin swept becomes an input
    # and a single output pays the rest to the reserve, no
    # change output needed.
    #
    # Used by:
    #   - app/worker.py — _sweep_deposit
    ############################################################

    def build_sweep_tx(self, deposit: DerivedKey, fee_rate_sat_vb: int = 10, coins: list = None):
        # STEP 1: every coin swept becomes an input
        # =========================================
        utxos = self.get_unspent(deposit.scripthash) if coins is None else coins
        if not utxos:
            return None

        inputs = []
        total_input = 0
        for utxo in utxos:
            inputs.append(Input(
                prev_txid=utxo['tx_hash'],
                output_n=utxo['tx_pos'],
                keys=deposit.key,
                value=int(utxo['value']),
                witness_type='segwit',
                network=self.bl_network,
            ))
            total_input += int(utxo['value'])


        # STEP 2: the fee of the one-output spend, and what is
        # left for the reserve
        # ====================================================
        amount_sat = total_input - spend_fee_sat(len(inputs), 1, fee_rate_sat_vb)
        if amount_sat <= DUST_LIMIT_SAT:
            return None


        # STEP 3: the single output to the reserve, signed
        # ================================================
        reserve_script = self._address_to_script(self.reserve.address)
        outputs = [Output(amount_sat, lock_script=reserve_script, network=self.bl_network)]

        tx = Transaction(inputs=inputs, outputs=outputs, network=self.bl_network, witness_type='segwit')
        tx.sign(deposit.key)
        raw_hex = tx.raw_hex()

        txid = Transaction.parse_hex(raw_hex).txid
        return txid, raw_hex, amount_sat






    ############################################################
    # build_refund_tx
    ############################################################
    #
    # Signs a transaction sending coins on a deposit address
    # back where they came from, each coin carrying the script
    # it goes back to (its refund_to, see sender_of): one output
    # per sender, each paying the fee of its own coins (see
    # refund_plan). Returns its txid, raw hex, the senders paid
    # with their amounts in satoshis, and the coins it spends —
    # or None when no sender's coins are worth more than dust
    # after their fee. A coin left out stays on the address.
    #
    # Built here and broadcast by the worker, which persists the
    # signed refund first — so a crash in between can only ever
    # lead to the same refund being broadcast again, never to a
    # second one.
    #
    # Used by:
    #   - app/worker.py — the coins an order sends back
    ############################################################

    def build_refund_tx(self, deposit: DerivedKey, coins: list, fee_rate_sat_vb: int = 10):
        # STEP 1: what goes back to whom
        # ==============================
        plan = refund_plan(coins, fee_rate_sat_vb)
        if not plan:
            return None

        spent = [coin for _refund_to, _amount, group in plan for coin in group]


        # STEP 2: the coins in, one output per sender out, signed
        # with the deposit address's key
        # =======================================================
        inputs = [Input(
            prev_txid=coin['tx_hash'],
            output_n=coin['tx_pos'],
            keys=deposit.key,
            value=int(coin['value']),
            witness_type='segwit',
            network=self.bl_network,
        ) for coin in spent]
        outputs = [Output(amount, lock_script=refund_to, network=self.bl_network) for refund_to, amount, _group in plan]

        tx = Transaction(inputs=inputs, outputs=outputs, network=self.bl_network, witness_type='segwit')
        tx.sign(deposit.key)
        raw_hex = tx.raw_hex()

        txid = Transaction.parse_hex(raw_hex).txid
        return txid, raw_hex, [(refund_to, amount) for refund_to, amount, _group in plan], spent
