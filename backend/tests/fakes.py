############################################################
#  [*] Test doubles
#
#  FakeWallet stands in for app.wallet.ExchangeWallet in the
#  service/worker tests: every chain query returns whatever
#  the test configured, and every mutation (broadcast) is
#  recorded for assertions. No sockets, no keys, no Electrum.
#  Its reserve can cover any order unless a test says
#  otherwise, and every deposit transaction has a sender a
#  refund goes back to.
#
#  The chain it serves can also be scripted the way a real one
#  moves: a payment received, mined, its block orphaned, the
#  transaction dropped by a double-spend — each verb applied
#  to BOTH views the wallet answers from (the address history
#  and the UTXO set), so a reorganisation test reads as the
#  timeline it plays. Payouts live on the same chain: a
#  successful broadcast puts the payout in the mempool, bury
#  confirms it to a depth, and drop loses it again.
#
#  CoinWallet goes one step further, for the orders that share
#  a reserve or are paid more than once: its payouts, sweeps
#  and refunds move the coins they spend — out of the reserve,
#  out of a deposit address, into the reserve, back to the
#  student — so a reserve runs short, refills and is competed
#  for the way a real one is.
#
#  Used by:
#    - tests/base.py — every ExchangeTestCase gets two
#    - tests/test_service.py, test_worker.py, test_reorg.py,
#      test_lifecycle.py, test_refunds.py, test_routes.py,
#      test_api_contract.py, test_app.py
#    - tests/test_reserve_shortfall.py, test_several_deposits.py
#      — CoinWallets
############################################################


from types import SimpleNamespace

from app.wallet import COIN, DUST_LIMIT_SAT, ReserveShortfall, format_coins, refund_plan, spend_fee_sat








############################################################
# FakeWallet
############################################################
#
# One chain's wallet, answering from tables the test fills in
# (or scripts with receive, mine, bury, orphan and drop) and
# recording what the code under test asked it to do: the
# payouts it built and everything it broadcast. Its addresses
# are recognisable strings of the chain's prefix, not real
# bech32 — the sender of a deposit transaction is named after
# it — and an output script is the address itself. Refunds
# are planned the way the real wallet plans them.
#
# Used by:
#   - tests/base.py — ExchangeTestCase, one per chain
############################################################

class FakeWallet:

    def __init__(self, hrp='knf'):
        self.hrp = hrp
        self.short_name = {'knf': 'KNF', 'tltc': 'tLTC4'}.get(hrp, hrp)   # the chain's ticker, as messages name it
        self.reserve = SimpleNamespace(
            index=0,
            key=None,
            address=f'{hrp}1qreserve',
            scripthash='reserve-scripthash',
        )

        # --- Configurable chain state (tests overwrite these) ---------------
        self.tip_height = 100
        self.unspent = {}                  # scripthash -> [utxo, ...]
        self.history = {}                  # scripthash -> [{tx_hash, height}]
        self.known_txs = set()             # txids the chain holds (mempool or block)
        self.tx_heights = {}               # txid -> block height, 0 = mempool
        self.reserve_balance = 10 ** 15    # what the reserve can spend, in satoshis
        self.senders = {}                  # deposit txid -> its sender, when not the default

        # --- What the wallet should do when asked to act --------------------
        self.payout_result = ('payout-txid', 'payout-raw-hex')
        self.payout_error = None           # raise this from build_payout_tx
        self.broadcast_error = None        # raise this from broadcast
        self.sweep_result = None           # returned from build_sweep_tx

        # --- Recorded calls for assertions -----------------------------------
        self.broadcasts = []
        self.payout_requests = []          # (to_address, amount_sat)
        self.raw_txids = {}                # raw hex of a built payout or refund -> its txid
        self.sweep_requests = []           # the coins each sweep was asked for (None: all)
        self.refunds_built = 0

    # --- Address helpers ------------------------------------------------------

    def derive(self, index):
        return SimpleNamespace(
            index=index,
            key=None,
            address=f'{self.hrp}1qdeposit{index}',
            scripthash=f'deposit-scripthash-{index}',
        )

    def is_valid_address(self, address):
        return address.startswith(f'{self.hrp}1q')

    # --- Chain queries ----------------------------------------------------------

    def get_tip_height(self):
        return self.tip_height

    def get_history(self, scripthash):
        return self.history.get(scripthash, [])

    def get_unspent(self, scripthash):
        return self.unspent.get(scripthash, [])

    def get_received_sat(self, scripthash):
        return sum(int(u['value']) for u in self.get_unspent(scripthash))

    def get_balance_sat(self, scripthash):
        confirmed = sum(int(u['value']) for u in self.get_unspent(scripthash) if u.get('height', 0) > 0)
        unconfirmed = sum(int(u['value']) for u in self.get_unspent(scripthash) if u.get('height', 0) <= 0)
        return {'confirmed': confirmed, 'unconfirmed': unconfirmed}

    def get_transaction(self, txid):
        return 'raw-hex' if txid in self.known_txs else None

    def reserve_balance_sat(self):
        return self.reserve_balance

    def sender_of(self, tx_hash):
        # Where a refund of the transaction's coins goes: a sender named
        # after it, unless the test named another — None when there is none
        # to find, an exception raised when the server does not hand the
        # transaction out
        sender = self.senders.get(tx_hash, f'{self.hrp}1qfrom-{tx_hash}')
        if isinstance(sender, Exception):
            raise sender
        return sender

    def address_of(self, script):
        return script

    def confirmations(self, txid, scripthash):
        if txid not in self.known_txs:
            return None
        height = self.tx_heights.get(txid, 0)
        return max(0, self.tip_height - height + 1) if height > 0 else 0

    def payout_confirmations(self, txid, address):
        return self.confirmations(txid, address)

    # --- Actions ------------------------------------------------------------------

    def build_payout_tx(self, to_address, amount_sat, fee_rate_sat_vb=10):
        self.payout_requests.append((to_address, amount_sat))
        if self.payout_error:
            raise self.payout_error
        txid, raw_hex = self.payout_result
        self.raw_txids[raw_hex] = txid
        return self.payout_result

    def build_sweep_tx(self, deposit, fee_rate_sat_vb=10, coins=None):
        self.sweep_requests.append(coins)
        return self.sweep_result

    def build_refund_tx(self, deposit, coins, fee_rate_sat_vb=10):
        plan = refund_plan(coins, fee_rate_sat_vb)
        if not plan:
            return None
        self.refunds_built += 1
        txid, raw_hex = f'refund-{self.refunds_built}', f'refund-{self.refunds_built}-raw'
        self.raw_txids[raw_hex] = txid
        return txid, raw_hex, [(to, amount) for to, amount, _group in plan], [coin for _to, _amount, group in plan for coin in group]

    def broadcast(self, raw_hex):
        if self.broadcast_error:
            raise self.broadcast_error
        self.broadcasts.append(raw_hex)
        # A payout the network accepted waits in its mempool
        if raw_hex in self.raw_txids:
            self.known_txs.add(self.raw_txids[raw_hex])
        return 'broadcast-txid'

    # --- Scripting the chain ---------------------------------------------------

    def receive(self, scripthash, tx_hash, value_sat, height=0, tx_pos=0):
        # A payment to an address, seen first at `height` (0 = in the mempool)
        self.unspent.setdefault(scripthash, []).append({
            'tx_hash': tx_hash, 'tx_pos': tx_pos, 'height': height, 'value': value_sat,
        })
        self.history.setdefault(scripthash, []).append({'tx_hash': tx_hash, 'height': height})

    def mine(self, tx_hash, height):
        # The transaction lands in the block at `height` — or lands again,
        # in another block, after a reorganisation
        for entry in self._entries(tx_hash):
            entry['height'] = height
        self.tx_heights[tx_hash] = height

    def bury(self, tx_hash, confirmations=2):
        # The transaction confirmed this deep under the current tip
        self.known_txs.add(tx_hash)
        self.tx_heights[tx_hash] = self.tip_height - confirmations + 1

    def orphan(self, tx_hash):
        # Its block is orphaned: the transaction falls back into the mempool
        self.mine(tx_hash, 0)

    def drop(self, tx_hash):
        # Double-spent, replaced or evicted: gone from every view for good
        for table in (self.unspent, self.history):
            for scripthash, entries in table.items():
                table[scripthash] = [entry for entry in entries if entry['tx_hash'] != tx_hash]
        self.known_txs.discard(tx_hash)
        self.tx_heights.pop(tx_hash, None)

    def _entries(self, tx_hash):
        return [entry
                for table in (self.unspent, self.history)
                for entries in table.values()
                for entry in entries
                if entry['tx_hash'] == tx_hash]








############################################################
# CoinWallet
############################################################
#
# A FakeWallet whose own transactions move the coins they
# spend. A payout is paid from the coins on the reserve,
# picked the way the real wallet picks them — confirmed ones
# first, as many as the amount and its fee need — and refused
# with the real wallet's sentences when they fall short; its
# change goes back to the reserve. A sweep carries the coins
# of a deposit address it is given (all of them by default)
# into the reserve, and a refund sends coins back to their
# senders the way the real wallet plans it. Each transaction
# gets a txid of its own (payout-1, sweep-1, refund-1, ...),
# and the reserve can spend what is on it.
#
# The network accepts a transaction only while no other one
# it accepted spends the same coins, and records every payout
# it accepts in payouts and every refund in refunds — what the
# students were really paid, and sent back. The server's view
# can lag behind the network the way an Electrum server's
# does, which polls the node's mempool and shows a broadcast
# only at its next refresh: with lagging set, what the network
# accepted reaches the view at catch_up.
#
# Only the student's and the operator's transactions are
# meant to be dropped here: dropping one of the exchange's
# own leaves the coins it spent spent.
#
# Used by:
#   - tests/test_reserve_shortfall.py
#   - tests/test_several_deposits.py
############################################################

class CoinWallet(FakeWallet):

    def __init__(self, hrp='knf'):
        super().__init__(hrp)

        # --- What the network accepted -------------------------------------
        self.payouts = []                  # (to_address, amount_sat) of each payout
        self.refunds = []                  # (to_address, amount_sat) of each refund output
        self.spent_by = {}                 # (tx_hash, tx_pos) -> txid spending it

        # --- How far the server's view lags --------------------------------
        self.lagging = False               # True: accepted txs show at catch_up()
        self.unseen = []                   # accepted, not in the view yet

        # --- What the exchange signed, by raw hex --------------------------
        self.signed = {}
        self.built = {'payout': 0, 'sweep': 0, 'refund': 0}

    # --- Scripting the reserve and the view ------------------------------------

    def fund_reserve(self, tx_hash, value_sat, height=90):
        # The operator tops the reserve up, the coins mined at `height`
        # (0 = still in the mempool)
        self.receive(self.reserve.scripthash, tx_hash, value_sat, height=height)

    def catch_up(self):
        # The server's next mempool refresh: everything the network accepted
        # shows in its view
        for tx in self.unseen:
            self._show(tx)
        self.unseen = []

    # --- Chain queries -----------------------------------------------------------

    def reserve_balance_sat(self):
        return sum(int(coin['value']) for coin in self.get_unspent(self.reserve.scripthash))

    # --- Actions ---------------------------------------------------------------

    def build_payout_tx(self, to_address, amount_sat, fee_rate_sat_vb=10):
        self.payout_requests.append((to_address, amount_sat))
        if self.payout_error:
            raise self.payout_error

        coins = sorted(self.get_unspent(self.reserve.scripthash), key=lambda coin: coin['height'] <= 0)
        if not coins:
            raise ReserveShortfall('Reserve address has no funds to pay out')

        # The real wallet's estimate: two outputs, the payout and the change
        fee_for = lambda count: spend_fee_sat(count, 2, fee_rate_sat_vb)
        inputs, have = [], 0
        for coin in coins:
            inputs.append(coin)
            have += coin['value']
            if have >= amount_sat + fee_for(len(inputs)):
                break

        need = amount_sat + fee_for(len(inputs))
        if have < need:
            raise ReserveShortfall(f'Insufficient reserve funds: have {format_coins(have / COIN)} {self.short_name}, '
                                   f'need {format_coins(need / COIN)} {self.short_name}')

        change = have - need
        return self._sign('payout', self.reserve.scripthash, inputs, [(to_address, amount_sat)],
                          change if change > DUST_LIMIT_SAT else 0)

    def build_sweep_tx(self, deposit, fee_rate_sat_vb=10, coins=None):
        coins = self.get_unspent(deposit.scripthash) if coins is None else coins
        if not coins:
            return None

        amount_sat = sum(coin['value'] for coin in coins) - spend_fee_sat(len(coins), 1, fee_rate_sat_vb)
        if amount_sat <= DUST_LIMIT_SAT:
            return None

        txid, raw_hex = self._sign('sweep', deposit.scripthash, coins, [], amount_sat)
        return txid, raw_hex, amount_sat

    def build_refund_tx(self, deposit, coins, fee_rate_sat_vb=10):
        plan = refund_plan(coins, fee_rate_sat_vb)
        if not plan:
            return None

        spent = [coin for _to, _amount, group in plan for coin in group]
        recipients = [(to, amount) for to, amount, _group in plan]
        txid, raw_hex = self._sign('refund', deposit.scripthash, spent, recipients, 0)
        return txid, raw_hex, recipients, spent

    def broadcast(self, raw_hex):
        tx = self.signed.get(raw_hex)
        if tx is None or self.broadcast_error:
            return super().broadcast(raw_hex)

        for coin in tx['inputs']:
            if self.spent_by.get(self._outpoint(coin), tx['txid']) != tx['txid']:
                raise RuntimeError("Electrum error: {'code': 1, 'message': "
                                   "'the transaction was rejected by network rules. txn-mempool-conflict'}")

        self.broadcasts.append(raw_hex)
        if tx['txid'] not in self.known_txs:
            # Accepted, for the first time: it waits in the mempool
            self.known_txs.add(tx['txid'])
            self.spent_by.update({self._outpoint(coin): tx['txid'] for coin in tx['inputs']})
            if tx['kind'] == 'payout':
                self.payouts.extend(tx['payees'])
            if tx['kind'] == 'refund':
                self.refunds.extend(tx['payees'])
            if self.lagging:
                self.unseen.append(tx)
            else:
                self._show(tx)
        return tx['txid']

    def bury(self, tx_hash, confirmations=2):
        # What it paid into the reserve confirms with it
        super().bury(tx_hash, confirmations)
        self.mine(tx_hash, self.tx_heights[tx_hash])

    # --- Bookkeeping -----------------------------------------------------------

    def _sign(self, kind, owner, inputs, payees, to_reserve):
        # A transaction spending `inputs` from the `owner` address: each of
        # `payees` paid its amount, `to_reserve` satoshis back to the reserve
        self.built[kind] += 1
        txid = f'{kind}-{self.built[kind]}'
        self.signed[f'{txid}-raw'] = {
            'txid': txid, 'kind': kind, 'owner': owner, 'inputs': list(inputs),
            'payees': list(payees), 'to_reserve': to_reserve,
        }
        return txid, f'{txid}-raw'

    def _show(self, tx):
        # An accepted transaction in the server's view: the coins it spends
        # gone from their address, every address it touches listing it in its
        # history, and what it pays the reserve waiting there in the mempool
        spent = {self._outpoint(coin) for coin in tx['inputs']}
        self.unspent[tx['owner']] = [coin for coin in self.unspent.get(tx['owner'], [])
                                     if self._outpoint(coin) not in spent]

        touched = {tx['owner'], self.reserve.scripthash} if tx['to_reserve'] else {tx['owner']}
        for scripthash in touched:
            self.history.setdefault(scripthash, []).append({'tx_hash': tx['txid'], 'height': 0})

        if tx['to_reserve']:
            self.unspent.setdefault(self.reserve.scripthash, []).append({
                'tx_hash': tx['txid'], 'tx_pos': len(tx['payees']), 'height': 0, 'value': tx['to_reserve'],
            })

    @staticmethod
    def _outpoint(coin):
        return coin['tx_hash'], coin['tx_pos']
