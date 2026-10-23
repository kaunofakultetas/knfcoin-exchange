############################################################
#  [*] Exchange service
#
#  The request-facing half of the exchange: order validation
#  and creation, server-side pricing, reserve snapshots and
#  order CRUD. The status machine that advances orders lives
#  in app/worker.py; one ExchangeService owns one OrderWorker
#  plus one ExchangeWallet per chain.
#
#  An order is only taken while the reserve that would pay it
#  out can cover it: what that reserve holds, less what it
#  already owes the orders paid into before. Each order is
#  answered with the refunds that sent its coins back, when
#  there are any.
#
#  All state lives in the SQLite orders table, so a restart
#  simply resumes where the previous process left off.
#
#  Used by:
#    - main.py       — create_app builds the one instance
#    - app/routes.py — every request handler
#    - app/worker.py — borrows the wallets, pricing and the
#                      order and refund helpers
############################################################


import json
import math
import time
import uuid
import logging
import threading

from . import config
from .database import get_db_connection
from .icons import icon_url
from .wallet import ExchangeWallet, COIN, format_coins, spend_fee_sat
from .worker import OrderWorker


logger = logging.getLogger('exchange.service')








############################################################
# Assets, pricing and limits
############################################################
#
# The frontend labels the two tradable coins with these exact
# strings, so the mapping to internal network keys lives here
# in one place. Anything not in this table is rejected at
# order creation.
############################################################

KNF = 'KNF Coin'
LTC = 'LTC Testnet'

ASSET_TO_NETWORK = {
    KNF: 'knf',
    LTC: 'ltc4',
}


# Per-asset order size limits (in whole coins). Keeps demo orders sane and
# above the network dust limit.
AMOUNT_LIMITS = {
    KNF: {'min': 0.001,  'max': 100000.0},
    LTC: {'min': 0.0001, 'max': 10000.0},
}


# How long a student has to pay before the order is abandoned. An order
# only ever expires while NOTHING has been received - as soon as any coins
# arrive the order proceeds with whatever was actually sent, even if that
# differs from the agreed amount (the payout scales with the deposit).
ORDER_TTL_MS = 30 * 60 * 1000








############################################################
# ValidationError
############################################################
#
# Raised for anything the student got wrong (bad amount, bad
# address, ...). The routes layer turns this into an HTTP 400
# with the message; any other exception becomes a 500.
#
# Used by:
#   - ExchangeService (below) — network_key, pair_rate and
#     create_order raise it
#   - app/routes.py — api_create_order answers it with a 400
############################################################

class ValidationError(Exception):
    pass








############################################################
# Unavailable
############################################################
#
# Raised when the exchange cannot take an order right now for
# a reason on its own side: the reserve that would pay it out
# cannot be read. The routes layer answers it with a 503 that
# carries the sentence.
#
# Used by:
#   - ExchangeService.create_order (below)
#   - app/routes.py — api_create_order answers it with a 503
############################################################

class Unavailable(Exception):
    pass








############################################################
# ExchangeService
############################################################
#
# Owns the wallets and the worker. Reading order state is
# lock-free; the only lock guards deposit-index allocation so
# two concurrent order creations can never receive the same
# deposit address.
#
# Used by:
#   - main.py — create_app, one instance for the app's life
############################################################

class ExchangeService:






    ############################################################
    # __init__
    ############################################################
    #
    # chains is the registry (network key -> ChainDefinition).
    # Wallets are built lazily on first use; the worker is
    # created here but only started by start_worker().
    #
    # Used by:
    #   - main.py — create_app
    ############################################################

    def __init__(self, chains: dict):
        self.chains = chains                  # network key -> ChainDefinition
        self.wallets = {}                     # network key -> ExchangeWallet (lazy)
        self.lock = threading.Lock()
        self.fee_rate = config.FEE_RATE_SATVB

        # network key -> what its reserve can still pay out (whole coins),
        # as the worker last read it; None (or missing) = unknown
        self.capacity = {}

        self.worker = OrderWorker(self)






    ############################################################
    # now
    ############################################################
    #
    # The current time in epoch milliseconds — the unit of
    # every timestamp in the orders table and of every deadline
    # the worker compares. One clock for the service and the
    # worker alike, which is what lets the tests freeze it.
    #
    # Used by:
    #   - create_order, update_order (below)
    #   - app/worker.py — deadlines, the payout back-off and the
    #     late-deposit window
    ############################################################

    def now(self) -> int:
        return int(time.time() * 1000)






    ############################################################
    # wallet_for
    ############################################################
    #
    # The wallet of one chain, by network key.
    #
    # Used by:
    #   - wallet_for_asset, log_reserve_addresses,
    #     reserves_snapshot, create_order (below)
    ############################################################

    def wallet_for(self, network_key: str) -> ExchangeWallet:
        # Wallets are created on first use and cached; building one derives
        # the reserve key, so chains an install never touches stay untouched.
        if network_key not in self.wallets:
            self.wallets[network_key] = ExchangeWallet(self.chains[network_key])
        return self.wallets[network_key]






    ############################################################
    # wallet_for_asset
    ############################################################
    #
    # The wallet of the chain an asset label trades on.
    #
    # Used by:
    #   - app/worker.py — every step that reads a chain or pays
    ############################################################

    def wallet_for_asset(self, asset: str) -> ExchangeWallet:
        return self.wallet_for(self.network_key(asset))






    ############################################################
    # network_key
    ############################################################
    #
    # The network key of an asset label the frontend sends; a
    # label not in ASSET_TO_NETWORK is the student's error and
    # raises ValidationError.
    #
    # Used by:
    #   - wallet_for_asset, create_order (below)
    #   - app/worker.py — the receiving chain's confirmation
    #     target for a payout
    ############################################################

    def network_key(self, asset: str) -> str:
        key = ASSET_TO_NETWORK.get(asset)
        if not key:
            raise ValidationError(f'Unsupported asset: {asset}')
        return key






    ############################################################
    # pair_rate
    ############################################################
    #
    # How much of to_asset one from_asset buys: the configured
    # KNF → tLTC4 rate one way, its inverse the other. Any other
    # pair — the same asset on both sides included — raises
    # ValidationError.
    #
    # Used by:
    #   - rates_snapshot, create_order (below)
    #   - app/worker.py — the rate locked when a deposit confirms
    ############################################################

    def pair_rate(self, from_asset: str, to_asset: str) -> float:
        # Only the KNF <-> tLTC4 pair is priced.
        if (from_asset, to_asset) == (KNF, LTC):
            return config.RATE_KNF_TO_LTC
        if (from_asset, to_asset) == (LTC, KNF):
            return 1.0 / config.RATE_KNF_TO_LTC
        raise ValidationError(f'Unsupported pair: {from_asset} -> {to_asset}')






    ############################################################
    # rates_snapshot
    ############################################################
    #
    # Both directions' live rates, keyed by the two labels
    # joined with "->", the per-asset amount limits — so the UI
    # shows live numbers and the same limits the backend
    # enforces — the logo URL of each asset, null for one
    # without a logo file, and how much of each asset the
    # exchange can still pay out (see payout_capacity_sat) as
    # the worker last read it, null when unknown. Nothing here
    # asks Electrum, so a slow server never slows the swap form.
    #
    # Used by:
    #   - app/routes.py — GET /api/exchange/rates
    ############################################################

    def rates_snapshot(self) -> dict:
        return {
            'pairs': {
                f'{KNF}->{LTC}': self.pair_rate(KNF, LTC),
                f'{LTC}->{KNF}': self.pair_rate(LTC, KNF),
            },
            'limits': AMOUNT_LIMITS,
            'icons': {asset: icon_url(network) for asset, network in ASSET_TO_NETWORK.items()},
            'capacity': {asset: self.capacity.get(network) for asset, network in ASSET_TO_NETWORK.items()},
        }






    ############################################################
    # start_worker
    ############################################################
    #
    # Starts the order worker's daemon thread (a no-op while it
    # already runs).
    #
    # Used by:
    #   - main.py — create_app
    ############################################################

    def start_worker(self):
        self.worker.start()






    ############################################################
    # stop_worker
    ############################################################
    #
    # Asks the worker thread to stop after its current pass and
    # waits for it.
    #
    # Used by:
    #   - nothing calls this at the moment (the worker tests stop
    #     the worker directly)
    ############################################################

    def stop_worker(self):
        self.worker.stop()






    ############################################################
    # log_reserve_addresses
    ############################################################
    #
    # Logs each chain's reserve (payout) address at startup.
    # Payouts are funded from these addresses, so an operator
    # needs to top them up. Deriving an address never touches
    # Electrum, so this works even while a chain's server is
    # still bootstrapping.
    #
    # Used by:
    #   - main.py — create_app, at startup
    ############################################################

    def log_reserve_addresses(self):
        logger.info('Reserve/payout addresses (fund these):')
        for key, chain in self.chains.items():
            try:
                logger.info('    %6s: %s', chain.short_name, self.wallet_for(key).reserve.address)
            except Exception as e:
                logger.error('    %s: could not derive reserve address: %s', key, e)






    ############################################################
    # reserves_snapshot
    ############################################################
    #
    # Snapshot of every chain's reserve (payout) wallet: its
    # address, its live on-chain balance, what it can still pay
    # out to a new order (available: the balance less what it
    # owes the orders paid into and a payout's fee) and the
    # chain's logo URL. Payouts are funded from these
    # addresses, so this is what an operator watches to know
    # which wallet to top up.
    #
    # The address is derived locally and always present; the
    # balance needs Electrum, so a chain whose server is down
    # (or still syncing) reports an `error` instead of numbers
    # rather than failing the whole snapshot.
    #
    # Used by:
    #   - app/routes.py — GET /api/exchange/reserves
    ############################################################

    def reserves_snapshot(self) -> list:
        asset_labels = {network: asset for asset, network in ASSET_TO_NETWORK.items()}
        reserves = []

        for key, chain in self.chains.items():
            wallet = self.wallet_for(key)
            entry = {
                'network':        key,
                'asset':          asset_labels.get(key),
                'short_name':     chain.short_name,
                'full_name':      chain.full_name,
                'block_explorer': chain.block_explorer,
                'icon':           icon_url(key),
                'address':        wallet.reserve.address,
                'confirmed':      None,
                'unconfirmed':    None,
                'available':      None,
                'error':          None,
            }

            try:
                # A syncing Electrum server happily answers "0" for every
                # address, which would look like an empty wallet - so check
                # it actually has a chain tip before trusting its balances.
                if wallet.get_tip_height() <= 0:
                    raise RuntimeError('Electrum server is still syncing (no chain tip yet)')

                balance = wallet.get_balance_sat(wallet.reserve.scripthash)
                spare = balance['confirmed'] + balance['unconfirmed'] - self.owed_sat(key)
                entry['confirmed'] = balance['confirmed'] / COIN
                entry['unconfirmed'] = balance['unconfirmed'] / COIN
                entry['available'] = max(0, spare - spend_fee_sat(1, 2, self.fee_rate)) / COIN
            except Exception as e:
                entry['error'] = str(e)

            reserves.append(entry)

        return reserves






    ############################################################
    # owed_sat
    ############################################################
    #
    # What one chain's reserve already owes, in satoshis: the
    # payouts, each with its fee, of the orders receiving on
    # that chain that have been paid into but not paid out yet.
    # An order with its rate locked owes what it locked; one
    # still confirming owes what its coins fetch at today's
    # rate. A payout already broadcast is in the reserve's
    # balance by now, and an order sending its coins back owes
    # nothing.
    #
    # Used by:
    #   - reserves_snapshot (above), payout_capacity_sat (below)
    ############################################################

    def owed_sat(self, network_key: str) -> int:
        assets = [asset for asset, key in ASSET_TO_NETWORK.items() if key == network_key]
        with get_db_connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM orders WHERE to_asset IN ({', '.join('?' * len(assets))}) AND tx_send_raw IS NULL "
                "AND status IN ('awaiting_confirmations', 'exchanging', 'sending')",
                assets,
            ).fetchall()

        owed = 0
        for row in rows:
            if row['status'] == 'sending':
                to_amount = row['to_amount']
            else:
                to_amount = row['received_amount'] * self.pair_rate(row['from_asset'], row['to_asset'])
            owed += int(round(to_amount * COIN)) + spend_fee_sat(1, 2, self.fee_rate)
        return owed






    ############################################################
    # payout_capacity_sat
    ############################################################
    #
    # The biggest payout one chain's reserve can still promise a
    # new order, in satoshis: what it can spend (see
    # ExchangeWallet.reserve_balance_sat), less what it owes,
    # less the fee of that payout itself — never below zero.
    # Raises when the reserve cannot be read.
    #
    # Used by:
    #   - refresh_capacity, create_order (below)
    ############################################################

    def payout_capacity_sat(self, network_key: str) -> int:
        spare = self.wallet_for(network_key).reserve_balance_sat() - self.owed_sat(network_key)
        return max(0, spare - spend_fee_sat(1, 2, self.fee_rate))






    ############################################################
    # refresh_capacity
    ############################################################
    #
    # Reads every chain's payout capacity again for the rates
    # answer, in whole coins — None for a chain whose reserve
    # cannot be read right now.
    #
    # Used by:
    #   - app/worker.py — _loop, at the end of every pass
    ############################################################

    def refresh_capacity(self):
        for key in self.chains:
            try:
                self.capacity[key] = self.payout_capacity_sat(key) / COIN
            except Exception:
                self.capacity[key] = None






    ############################################################
    # _next_deposit_index
    ############################################################
    #
    # Each order gets a unique HD child index so its deposit
    # address is unique. The counter lives in the meta table
    # and starts at 1 (index 0 is the reserve); allocation is
    # guarded by self.lock.
    #
    # Used by:
    #   - create_order (below)
    ############################################################

    def _next_deposit_index(self) -> int:
        with self.lock, get_db_connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'next_deposit_index'").fetchone()
            index = int(row['value']) if row else 1

            conn.execute(
                "INSERT INTO meta (key, value) VALUES ('next_deposit_index', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                [str(index + 1)],
            )
            conn.commit()

        return index






    ############################################################
    # create_order
    ############################################################
    #
    # Validates the student's request, makes sure the reserve
    # that would pay it out can cover it, derives a fresh
    # deposit address on the FROM chain and stores the order as
    # awaiting_deposit, quoted at the current rate; the worker
    # takes it from there. Answers the stored row. Every
    # refusal is a ValidationError carrying the sentence the
    # swap form shows; a reserve that cannot be read is an
    # Unavailable, with its own.
    #
    # Used by:
    #   - app/routes.py — POST /api/exchange/orders
    ############################################################

    def create_order(self, payload: dict) -> dict:
        # STEP 1: the request's three strings, trimmed
        # ============================================
        from_asset = (payload.get('from_asset') or '').strip()
        to_asset = (payload.get('to_asset') or '').strip()
        destination = (payload.get('destination') or '').strip()


        # STEP 2: validate the pair
        # =========================
        from_net = self.network_key(from_asset)
        to_net = self.network_key(to_asset)
        rate = self.pair_rate(from_asset, to_asset)   # also rejects from == to


        # STEP 3: validate the amount
        # ===========================
        try:
            from_amount = float(payload.get('from_amount'))
        except (TypeError, ValueError):
            raise ValidationError('from_amount must be a number')

        limits = AMOUNT_LIMITS[from_asset]
        if not (limits['min'] <= from_amount <= limits['max']):
            raise ValidationError(
                f"Amount must be between {limits['min']} and {limits['max']} {from_asset}"
            )


        # STEP 4: validate the destination address — it must be
        # a valid address on the chain the student RECEIVES on,
        # and it must not be an address the exchange itself
        # controls: paying out to our own reserve would burn the
        # coins, and paying out to another order's deposit
        # address would falsely trigger that order
        # ======================================================
        if not self.wallet_for(to_net).is_valid_address(destination):
            raise ValidationError(f'Invalid {to_asset} destination address')

        if destination == self.wallet_for(to_net).reserve.address:
            raise ValidationError('Destination cannot be an exchange address - use your own wallet address')

        with get_db_connection() as conn:
            row = conn.execute('SELECT 1 FROM orders WHERE deposit_address = ? LIMIT 1', [destination]).fetchone()
        if row:
            raise ValidationError('Destination cannot be an exchange address - use your own wallet address')


        # STEP 5: the reserve of the chain the student receives on
        # must cover the payout — what it holds, less what it owes
        # the orders paid into before and the payout's fee. An
        # order it cannot cover is refused here, before the
        # student pays anything; one whose reserve cannot be read
        # is not taken either
        # ========================================================
        try:
            capacity_sat = self.payout_capacity_sat(to_net)
        except Exception as e:
            logger.warning('Could not read the %s reserve for a new order: %s', to_net, e)
            raise Unavailable(f'The exchange cannot check its {to_asset} reserve right now - please try again in a minute')

        if int(round(from_amount * rate * COIN)) > capacity_sat:
            raise ValidationError(self._capacity_refusal(from_asset, to_asset, rate, capacity_sat))


        # STEP 6: derive a unique deposit address on the FROM chain
        # =========================================================
        index = self._next_deposit_index()
        deposit = self.wallet_for(from_net).derive(index)


        # STEP 7: price and persist
        # =========================
        now = self.now()
        order = {
            'id':                 uuid.uuid4().hex[:8].upper(),
            'pair':               f'{from_asset} -> {to_asset}',
            'from_asset':         from_asset,
            'to_asset':           to_asset,
            'from_amount':        from_amount,
            'to_amount':          from_amount * rate,
            'rate':               rate,
            'destination':        destination,
            'status':             'awaiting_deposit',
            'confirm_target':     self.chains[from_net].confirm_target,
            'deposit_index':      index,
            'deposit_address':    deposit.address,
            'deposit_scripthash': deposit.scripthash,
            'created_at':         now,
            'updated_at':         now,
            'expires_at':         now + ORDER_TTL_MS,
        }

        columns = ', '.join(order)
        placeholders = ', '.join(f':{k}' for k in order)
        with get_db_connection() as conn:
            conn.execute(f'INSERT INTO orders ({columns}) VALUES ({placeholders})', order)
            conn.commit()

        return self.get_order(order['id'])






    ############################################################
    # _capacity_refusal
    ############################################################
    #
    # The sentence an order its reserve cannot cover is refused
    # with: the most the student can send instead, rounded down
    # to the satoshi — or, when even the smallest order is too
    # much, that the exchange cannot pay out that asset now.
    #
    # Used by:
    #   - create_order (above)
    ############################################################

    def _capacity_refusal(self, from_asset: str, to_asset: str, rate: float, capacity_sat: int) -> str:
        most = math.floor(capacity_sat / rate) / COIN
        if most < AMOUNT_LIMITS[from_asset]['min']:
            return f'The exchange cannot pay out {to_asset} right now - please try again later'
        return f'The exchange can take at most {format_coins(most)} {from_asset} right now'






    ############################################################
    # list_orders
    ############################################################
    #
    # The latest orders, newest first, as the API answers them
    # (see _order_answer); the caller bounds the limit.
    #
    # Used by:
    #   - app/routes.py — GET /api/exchange/orders
    ############################################################

    def list_orders(self, limit: int = 20) -> list:
        with get_db_connection() as conn:
            cur = conn.execute('SELECT * FROM orders ORDER BY created_at DESC LIMIT ?', [limit])
            return [self._order_answer(conn, row) for row in cur.fetchall()]






    ############################################################
    # get_order
    ############################################################
    #
    # One order as the API answers it (see _order_answer), or
    # None for an id the database does not know.
    #
    # Used by:
    #   - create_order (above) — answers the stored row
    #   - app/routes.py — GET /api/exchange/orders/<id>
    ############################################################

    def get_order(self, order_id: str):
        with get_db_connection() as conn:
            row = conn.execute('SELECT * FROM orders WHERE id = ?', [order_id]).fetchone()
            return self._order_answer(conn, row) if row else None






    ############################################################
    # _order_answer
    ############################################################
    #
    # An order row as a plain dict of its columns, plus the logo
    # URLs of the two coins it trades — from_icon and to_icon,
    # null for a coin without a logo file — and its refunds,
    # oldest first: each one's txid, whether it has confirmed,
    # when it was made and who it pays what (recipients, the
    # address null for a script the exchange cannot name). The
    # logos are looked up at every read, never stored, so a
    # logo dropped into the icons folder shows on the orders
    # made before it too.
    #
    # Used by:
    #   - list_orders, get_order (above) — read on their
    #     connection
    ############################################################

    def _order_answer(self, conn, row) -> dict:
        order = dict(row)
        order['from_icon'] = icon_url(ASSET_TO_NETWORK.get(order['from_asset']))
        order['to_icon'] = icon_url(ASSET_TO_NETWORK.get(order['to_asset']))
        order['refunds'] = [{
            'txid':       refund['txid'],
            'confirmed':  refund['state'] == 'confirmed',
            'created_at': refund['created_at'],
            'recipients': json.loads(refund['recipients']),
        } for refund in conn.execute('SELECT * FROM refunds WHERE order_id = ? ORDER BY created_at, rowid', [order['id']])]
        return order






    ############################################################
    # update_order
    ############################################################
    #
    # Writes the given columns onto an order. The keys of the
    # dict become column names in the SQL (only the values are
    # bound), so they must only ever come from code, never from
    # a request. updated_at is set on the caller's dict itself
    # — with no columns given, it is all that changes.
    #
    # Used by:
    #   - app/worker.py — every step of the lifecycle
    #   - add_refund, confirm_refund, drop_refund (below) — the
    #     order's update time
    ############################################################

    def update_order(self, order_id: str, updates: dict):
        # Always bump updated_at so the frontend can tell something changed.
        updates['updated_at'] = self.now()
        set_clause = ', '.join(f'{key} = ?' for key in updates)

        with get_db_connection() as conn:
            conn.execute(f'UPDATE orders SET {set_clause} WHERE id = ?', [*updates.values(), order_id])
            conn.commit()






    ############################################################
    # add_refund
    ############################################################
    #
    # Records a signed refund of an order's coins as pending,
    # with the outpoints it spends and who it pays what — done
    # BEFORE the refund is broadcast, so a crash in between
    # sends the very same one out again.
    #
    # Used by:
    #   - app/worker.py — the coins an order sends back
    ############################################################

    def add_refund(self, order_id: str, txid: str, raw_hex: str, coins: list, recipients: list):
        now = self.now()
        with get_db_connection() as conn:
            conn.execute(
                'INSERT INTO refunds (txid, order_id, raw, coins, recipients, state, created_at, updated_at) '
                "VALUES (?, ?, ?, ?, ?, 'pending', ?, ?)",
                [txid, order_id, raw_hex, json.dumps(coins), json.dumps(recipients), now, now],
            )
            conn.commit()

        # The order's own row changes too, so a page polling it sees the refund
        self.update_order(order_id, {})






    ############################################################
    # refunds_of
    ############################################################
    #
    # Every refund of one order, oldest first, its coins and
    # recipients read back from their JSON.
    #
    # Used by:
    #   - app/worker.py — the refunds an order follows and the
    #     coins they hold
    ############################################################

    def refunds_of(self, order_id: str) -> list:
        with get_db_connection() as conn:
            rows = conn.execute('SELECT * FROM refunds WHERE order_id = ? ORDER BY created_at, rowid', [order_id]).fetchall()
        return [dict(row, coins=json.loads(row['coins']), recipients=json.loads(row['recipients'])) for row in rows]






    ############################################################
    # confirm_refund
    ############################################################
    #
    # A refund has confirmed as deep as a deposit must: it is
    # done.
    #
    # Used by:
    #   - app/worker.py — following a refund
    ############################################################

    def confirm_refund(self, order_id: str, txid: str):
        with get_db_connection() as conn:
            conn.execute("UPDATE refunds SET state = 'confirmed', updated_at = ? WHERE txid = ?", [self.now(), txid])
            conn.commit()
        self.update_order(order_id, {})






    ############################################################
    # drop_refund
    ############################################################
    #
    # Forgets a refund the chain refused for good (its coins were
    # spent by something else): those of its coins still on the
    # address are free to be sent back again.
    #
    # Used by:
    #   - app/worker.py — following a refund
    ############################################################

    def drop_refund(self, order_id: str, txid: str):
        with get_db_connection() as conn:
            conn.execute('DELETE FROM refunds WHERE txid = ?', [txid])
            conn.commit()
        self.update_order(order_id, {})
