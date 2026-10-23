############################################################
#  [*] Order worker
#
#  The background thread that drives every order through its
#  lifecycle, one idempotent step per tick:
#
#    awaiting_deposit -> awaiting_confirmations -> exchanging
#                     -> sending -> completed
#
#  plus the side-exits:
#    expired    — nothing was received before the deadline
#    refunding  — the order cannot go through (its reserve
#      -> refunded cannot cover the payout, or the payout would
#                 be below the dust limit), so its coins go back
#                 to the addresses they came from
#    failed     — its coins cannot be sent back either: too
#                 few to pay a refund's fee, or no sender to
#                 find (a coinbase, a transaction that cannot
#                 be read)
#    reversed   — completed, and then a reorganisation took a
#                 deposit the payout paid for back out of the
#                 chain: the exchange paid for coins it lost
#
#  An order is completed only once its payout has confirmed on
#  the receiving chain as deeply as a deposit must on its own;
#  until then a broadcast payout keeps the order "sending". A
#  refund is followed the same way, to the depth a deposit
#  needs on the chain it pays back on. Where coins go back is
#  read from the deposits' transactions: a chain server that
#  does not hand them out (an outage, a node keeping no
#  transaction index) holds a refund back — tried again every
#  REFUND_RETRY_MS — and never fails the order.
#
#  The rate lock fixes which coins on the deposit address the
#  payout pays for (paid_coins). A coin that arrives after it
#  is not exchanged: once the order is done it is sent back to
#  its sender, like every coin of an order that could not go
#  through.
#
#  The chain can change its mind at every step — a block
#  orphaned, a transaction double-spent or replaced — so no
#  step trusts an earlier step's reading: confirmations count
#  every coin on the deposit address, the rate lock waits
#  until each of them is deep enough, the payout first checks
#  that the coins it pays for are still there, a payout the
#  chain lost before confirming is broadcast again, and an
#  order whose deposit vanished goes back as far as it has to,
#  its received amount cleared. Every order's address is still
#  watched for a day after its deadline, so coins arriving late
#  — or mined after all once a reorganisation took them away —
#  are not stranded: an expired order takes them up, one that
#  is done sends them back. A payout cannot be called back, so
#  a completed order is watched for its deposit too: one the
#  chain took back makes it reversed, and it is completed
#  again should the chain bring the deposit back.
#
#  After an order completes, the coins its payout paid for are
#  swept from the per-order address into the chain's reserve
#  (tracked by sweep_state), so incoming deposits keep funding
#  future payouts instead of piling up on dead addresses.
#
#  Every step persists its result immediately, so a crash at
#  any point simply resumes where the previous process left
#  off. The worker never talks HTTP: it reads and writes the
#  orders table and queries the chains through the service's
#  wallets.
#
#  Used by:
#    - app/service.py — ExchangeService owns one OrderWorker
############################################################


import json
import time
import logging
import threading

from .database import get_db_connection
from .wallet import ExchangeWallet, COIN, DUST_LIMIT_SAT, ReserveShortfall, format_coins, spend_fee_sat


logger = logging.getLogger('exchange.worker')


# How often the worker wakes up to advance orders.
WORKER_INTERVAL_S = 5

# How long to wait before retrying a payout that failed (e.g. because the
# Electrum server could not be reached), so a stuck order does not hammer
# Electrum every tick.
PAYOUT_RETRY_MS = 30 * 1000

# How long to wait before retrying a refund that could not be prepared (the
# chain's Electrum server not handing out the deposits' transactions, say).
REFUND_RETRY_MS = 30 * 1000

# How long after its deadline an order's deposit address is still watched
# for coins that arrive late, and how often it is looked at - each watched
# order costs one Electrum query per look. Late coins take an expired order
# back into the lifecycle; an order that is done sends them back.
LATE_DEPOSIT_WINDOW_MS = 24 * 60 * 60 * 1000
LATE_DEPOSIT_CHECK_MS = 60 * 1000








############################################################
# OrderWorker
############################################################
#
# A single daemon thread owned by the ExchangeService. It
# borrows the service's wallets, pricing and order helpers;
# everything status-machine-related lives here. One method
# per status moves an order at most one step forward; the
# loop dispatches to them.
#
# Used by:
#   - app/service.py — ExchangeService creates one
############################################################

class OrderWorker:






    ############################################################
    # __init__
    ############################################################
    #
    # Ties the worker to its service; the thread itself only
    # exists once start() runs.
    #
    # Used by:
    #   - app/service.py — ExchangeService.__init__
    ############################################################

    def __init__(self, service):
        self.service = service
        self.thread = None
        self.stop_flag = False

        # When the addresses of the orders no step follows are next due a look
        self._late_check_due = 0

        # Deposit txid -> the output script its coins go back to (None: there
        # is none to find); asked of the chain once per transaction
        self._senders = {}

        # Refunding order id -> when its refund is next tried, after a pass
        # that could not be made
        self._refund_retry_due = {}






    ############################################################
    # start
    ############################################################
    #
    # Starts the loop on its daemon thread — a no-op while it
    # already runs, so the worker never races itself.
    #
    # Used by:
    #   - app/service.py — start_worker
    ############################################################

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_flag = False
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        logger.info('Worker thread started')






    ############################################################
    # stop
    ############################################################
    #
    # Asks the loop to stop after its current pass and waits
    # for the thread up to 5 seconds.
    #
    # Used by:
    #   - app/service.py — stop_worker, which nothing calls at
    #     the moment
    ############################################################

    def stop(self):
        self.stop_flag = True
        if self.thread:
            self.thread.join(timeout=5)






    ############################################################
    # _loop
    ############################################################
    #
    # The worker thread's life: a pass every WORKER_INTERVAL_S
    # until stopped. Each pass reads the orders still in motion
    # and hands each to the step of its status, then looks at
    # the addresses of the orders no step follows any more for
    # late coins, sweeps paid deposits into the reserves and
    # reads again what each reserve can still pay out.
    #
    # Used by:
    #   - start (above) — the thread's target
    ############################################################

    def _loop(self):
        handlers = {
            'awaiting_deposit':        self._check_deposit,
            'awaiting_confirmations':  self._check_confirmations,
            'exchanging':              self._lock_exchange_rate,
            'sending':                 self._send_payout,
            'refunding':               self._refund_order,
        }

        # Two layers of protection: a per-order try so one bad order never
        # blocks the others, and an outer try so nothing (e.g. a transient
        # database error) can kill the worker thread itself.
        while not self.stop_flag:
            try:
                with get_db_connection() as conn:
                    cur = conn.execute(
                        f"SELECT * FROM orders WHERE status IN ({', '.join('?' * len(handlers))})",
                        list(handlers),
                    )
                    orders = [dict(row) for row in cur.fetchall()]

                for order in orders:
                    try:
                        handlers[order['status']](order)
                    except Exception as e:
                        logger.error('Error on order %s: %s', order['id'], e)

                self._watch_late_coins()
                self._sweep_finished_orders()
                self.service.refresh_capacity()

            except Exception as e:
                logger.error('Loop error: %s', e)

            time.sleep(WORKER_INTERVAL_S)






    ############################################################
    # _check_deposit
    ############################################################
    #
    # awaiting_deposit: watches ONLY this order's own deposit
    # address. The FIRST deposit that shows up moves the order
    # forward, whatever its size: the payout is recomputed from
    # the actual received amount at rate-lock time, so a
    # student who sends less (or more) than agreed simply swaps
    # that amount instead of leaving the order stuck.
    #
    # The chain is always queried BEFORE the deadline is
    # applied, so a deposit landing in the final seconds (or
    # seen late because Electrum was briefly unreachable) can
    # never be swallowed by an expiry that fired first. Expiry
    # only ever happens on a positive "nothing has been
    # received" answer from Electrum.
    #
    # Used by:
    #   - _loop (above) — awaiting_deposit orders
    #   - _watch_late_coins (below) — an expired order whose
    #     address holds coins
    ############################################################

    def _check_deposit(self, order: dict):
        # STEP 1: what has arrived — asked before the deadline is
        # applied
        # =======================================================
        wallet = self.service.wallet_for_asset(order['from_asset'])
        received_sat = wallet.get_received_sat(order['deposit_scripthash'])
        past_deadline = self.service.now() > order['expires_at']


        # STEP 2: nothing yet — the order expires once its deadline
        # has passed
        # =========================================================
        if received_sat <= 0:
            if past_deadline:
                self.service.update_order(order['id'], {'status': 'expired'})
            return


        # STEP 3: coins arrived — record them and the transaction
        # whose confirmations are counted
        # =======================================================
        received_amount = received_sat / COIN

        history = wallet.get_history(order['deposit_scripthash'])
        if not history:
            return

        # The newest history entry stands in for "the deposit tx" whose
        # confirmations are tracked. With several deposit transactions this
        # tracks only the latest — good enough, because the payout amount is
        # re-read from the address total, never from this single tx.
        deposit_tx = history[-1]['tx_hash']
        logger.info('Deposit seen for %s: %s (%s)', order['id'], deposit_tx, received_amount)
        self.service.update_order(order['id'], {
            'status': 'awaiting_confirmations',
            'tx_deposit_id': deposit_tx,
            'received_amount': received_amount,
            'confirm_count': 0,
        })






    ############################################################
    # _check_confirmations
    ############################################################
    #
    # awaiting_confirmations: counts the deposit's
    # confirmations and moves the order on to the rate lock
    # once every coin on the address is as deep as the order's
    # confirm_target. A recorded deposit transaction that left
    # the address history sends the order back to awaiting its
    # deposit.
    #
    # Used by:
    #   - _loop (above) — awaiting_confirmations orders
    ############################################################

    def _check_confirmations(self, order: dict):
        # STEP 1: is the recorded deposit transaction still there?
        # ========================================================
        wallet = self.service.wallet_for_asset(order['from_asset'])
        history = wallet.get_history(order['deposit_scripthash'])

        # The recorded deposit tx vanished from the address history (chain
        # reorg or a replaced transaction): fall back to watching the
        # deposit address from scratch rather than polling a ghost tx
        # forever. Whatever is really on the address will be re-detected.
        if order['tx_deposit_id'] not in {h['tx_hash'] for h in history}:
            logger.warning('Deposit tx for %s disappeared (reorg?) -> re-checking deposit', order['id'])
            self._send_back_to_awaiting_deposit(order)
            return


        # STEP 2: count the coins and their confirmations
        # ===============================================
        # Every coin on the address counts, the youngest deciding: a top-up
        # sent during this phase must reach the target too before the order
        # moves on, since the payout pays for it as well. The figures are
        # kept fresh for the GUI, which shows them live - but a momentarily
        # empty answer from Electrum changes nothing, it must not wipe an
        # amount we have already seen.
        received_sat, confs, _coins = self._deposit_coins(wallet, order)
        if received_sat <= 0:
            return


        # STEP 3: record the count — on to the rate lock once deep
        # enough
        # ========================================================
        target = order['confirm_target'] or 1
        updates = {'confirm_count': confs, 'received_amount': received_sat / COIN}

        if confs >= target:
            logger.info('Order %s confirmed (%s/%s) -> exchanging', order['id'], confs, target)
            updates['status'] = 'exchanging'

        self.service.update_order(order['id'], updates)






    ############################################################
    # _lock_exchange_rate
    ############################################################
    #
    # exchanging: freezes the rate that will actually be paid
    # out — the current market rate at the moment the deposit
    # confirmed, stored on the order as locked_rate — and prices
    # the payout from how much actually arrived, not from the
    # quote shown at creation. The coins it counted become the
    # ones the payout pays for (paid_coins): whatever arrives
    # from now on is sent back, not exchanged.
    #
    # The received amount is RE-READ from the chain here rather
    # than trusted from the value recorded at first sight: the
    # deposit is confirmed by now, so this reading is stable,
    # whereas the earlier one could have caught Electrum
    # mid-block (which once reported a mempool tx and its
    # confirmed copy simultaneously, doubling the apparent
    # deposit and triggering a full payout for a half deposit).
    #
    # Used by:
    #   - _loop (above) — exchanging orders
    ############################################################

    def _lock_exchange_rate(self, order: dict):
        # STEP 1: re-read the deposit from the chain
        # ==========================================
        wallet = self.service.wallet_for_asset(order['from_asset'])
        received_sat, confs, coins = self._deposit_coins(wallet, order)
        if received_sat <= 0:
            # The chain disagrees that anything arrived - go back to watching
            # the deposit address instead of paying out on stale data.
            logger.warning('Order %s: deposit vanished before rate lock -> re-checking deposit', order['id'])
            self._send_back_to_awaiting_deposit(order)
            return


        # STEP 2: every coin deep enough, or back to counting
        # ===================================================
        # Nothing is paid for coins that could still vanish: when one of them
        # is not deep enough any more (an orphaned block put the deposit back
        # into the mempool) or not yet (an unconfirmed top-up arrived after
        # the count), the order counts confirmations again instead.
        target = order['confirm_target'] or 1
        if confs < target:
            logger.warning('Order %s: deposit not confirmed deep enough at rate lock (%s/%s) -> counting again',
                           order['id'], confs, target)
            self.service.update_order(order['id'], {
                'status': 'awaiting_confirmations',
                'confirm_count': confs,
                'received_amount': received_sat / COIN,
            })
            return


        # STEP 3: lock the rate, price the payout from what
        # arrived and fix the coins it pays for
        # =================================================
        received_amount = received_sat / COIN
        rate = self.service.pair_rate(order['from_asset'], order['to_asset'])
        to_amount = received_amount * rate
        logger.info('Exchanging order %s at rate %s: %s %s -> %s %s',
                    order['id'], rate, received_amount, order['from_asset'], to_amount, order['to_asset'])

        self.service.update_order(order['id'], {
            'status': 'sending',
            'locked_rate': rate,
            'received_amount': received_amount,
            'to_amount': to_amount,
            'paid_coins': json.dumps(sorted(self._outpoint(coin) for coin in coins)),
        })






    ############################################################
    # _send_payout
    ############################################################
    #
    # sending: pays the locked amount out to the student's
    # destination. A payout already built by an earlier pass is
    # followed to its confirmation, never built twice; a new
    # one is built only while the coins it pays for are still
    # on the deposit address, and is persisted before it is
    # broadcast. A failure to get it out (Electrum unreachable,
    # say) is recorded on the order, which stays "sending" and
    # retries after a back-off. A payout that cannot be made at
    # all — the reserve cannot cover it, or the amount is below
    # the dust limit — sends the order's coins back instead;
    # coins too few to be sent back either fail the order.
    #
    # Used by:
    #   - _loop (above) — sending orders
    ############################################################

    def _send_payout(self, order: dict):
        # STEP 1: back off between attempts — a payout that keeps
        # failing (an Electrum server out of reach, say) is
        # retried every PAYOUT_RETRY_MS, not every tick
        # =======================================================
        if order['error'] and self.service.now() - order['updated_at'] < PAYOUT_RETRY_MS:
            return


        # STEP 2: the amount in satoshis — below the network dust
        # limit it can never be broadcast, so the order does not
        # go through: its coins are sent back, or, too few to be
        # sent back as well, the order fails with the reason
        # =======================================================
        wallet = self.service.wallet_for_asset(order['to_asset'])
        amount_sat = int(round(order['to_amount'] * COIN))

        if amount_sat <= DUST_LIMIT_SAT:
            # The smallest payout the network takes is one satoshi over the dust limit
            reason = (f"Received amount is too small to pay out (a payout of {format_coins(amount_sat / COIN)} "
                      f"{order['to_asset']} is below the network's minimum of "
                      f"{format_coins((DUST_LIMIT_SAT + 1) / COIN)} {order['to_asset']})")
            if self._worth_sending_back(order):
                self._start_refund(order, reason)
            else:
                self.service.update_order(order['id'], {'status': 'failed', 'error': reason, 'paid_coins': None})
            return


        # STEP 3: pay — follow the payout an earlier pass built,
        # or build, persist and broadcast a new one
        # ======================================================
        try:
            if order['tx_send_raw']:
                # A previous pass already built (and possibly broadcast) the
                # payout - follow that one instead of ever building a second.
                self._finish_pending_payout(order, wallet)
                return

            # The coins this payout pays for must still be where the rate
            # lock counted them - a payout is never built on a vanished deposit
            if not self._deposit_still_backs(order):
                return

            # Persist the signed transaction BEFORE broadcasting: if we crash
            # between these two steps, the next pass rebroadcasts this exact
            # transaction (same txid) - a double payout is impossible.
            txid, raw_hex = wallet.build_payout_tx(order['destination'], amount_sat, self.service.fee_rate)
            self.service.update_order(order['id'], {'tx_send_id': txid, 'tx_send_raw': raw_hex})

            # Broadcast is not yet paid: the order stays "sending" until the
            # payout has confirmed (_finish_pending_payout, on later passes)
            wallet.broadcast(raw_hex)
            logger.info('Payout for %s broadcast: %s', order['id'], txid)
            if order['error']:
                self.service.update_order(order['id'], {'error': None})

        except ReserveShortfall as e:
            # An answer, not an outage: the reserve cannot pay this - so the
            # order does not go through, and its coins go back
            logger.warning('Payout for %s cannot be covered (%s) -> sending its coins back', order['id'], e)
            self._start_refund(order, f"The exchange's {order['to_asset']} reserve could not cover the payout "
                                      f"of {format_coins(order['to_amount'])} {order['to_asset']}")

        except Exception as e:
            # No answer (Electrum unreachable, a broadcast that did not get
            # through, ...): record the reason and leave the order in
            # "sending" so it retries
            logger.error('Payout failed for %s: %s', order['id'], e)
            self.service.update_order(order['id'], {'error': str(e)})






    ############################################################
    # _finish_pending_payout
    ############################################################
    #
    # Follows a payout whose signed transaction is persisted: it
    # completes the order once confirmed as deep as the
    # receiving chain asks of a deposit. Seen on its way before
    # that, it clears a failure recorded while getting it out —
    # the pages show a payout out with no failure on record as
    # done, its confirmations still to come. While the
    # destination's history - chain and mempool - does not hold
    # it at all, it never got out (a crash or a dropped
    # connection mid-send) or a reorganisation or the mempool
    # lost it: it is broadcast again, always the very same
    # transaction (same txid), so it can never pay twice. Only a
    # payout whose inputs were provably spent elsewhere is
    # discarded, for the next pass to build anew.
    #
    # Used by:
    #   - _send_payout (above)
    ############################################################

    def _finish_pending_payout(self, order: dict, wallet: ExchangeWallet):
        # STEP 1: how deep the payout lies — the order completes once
        # it is deep enough
        # ===========================================================
        txid = order['tx_send_id']
        confs = wallet.payout_confirmations(txid, order['destination'])

        if confs is not None:
            target = self._payout_target(order)
            if confs >= target:
                logger.info('Payout for %s confirmed (%s/%s): %s', order['id'], confs, target, txid)
                self.service.update_order(order['id'], {'status': 'completed', 'error': None})
            elif order['error']:
                self.service.update_order(order['id'], {'error': None})
            return


        # STEP 2: nowhere to be seen — broadcast the very same
        # transaction again
        # ====================================================
        try:
            wallet.broadcast(order['tx_send_raw'])
            logger.info('Payout for %s (re)broadcast: %s', order['id'], txid)
            if order['error']:
                self.service.update_order(order['id'], {'error': None})

        except Exception as e:
            # Classify by message text - fragile against Electrum version
            # changes, but the protocol offers nothing better, and a
            # misclassification fails safe (raises and retries later).
            message = str(e).lower()

            # "Already known": the network has it after all - wait for it to
            # show up in the history and confirm.
            if 'already' in message or 'duplicate' in message:
                return

            # The inputs were spent by something else (e.g. another payout
            # consumed the same reserve UTXOs before the crash): this
            # transaction can never confirm, so discard it and let the next
            # pass build a fresh one from the current UTXO set.
            if 'missingorspent' in message or 'conflict' in message or 'bad-txns' in message:
                logger.warning('Pending payout for %s conflicted - rebuilding', order['id'])
                self.service.update_order(order['id'], {
                    'tx_send_id': None,
                    'tx_send_raw': None,
                    'error': 'Previous payout attempt conflicted - rebuilding',
                })
                return

            raise






    ############################################################
    # _deposit_coins
    ############################################################
    #
    # Every coin on the order's deposit address: their total in
    # satoshis, the confirmations of the youngest - 0 while
    # one waits in the mempool, and 0 for an address that holds
    # nothing - and the coins themselves. Confirmations come
    # from block heights because Electrum servers do not
    # reliably return a "confirmations" field.
    #
    # Used by:
    #   - _check_confirmations, _lock_exchange_rate (above)
    ############################################################

    def _deposit_coins(self, wallet: ExchangeWallet, order: dict):
        utxos = wallet.get_unspent(order['deposit_scripthash'])
        if not utxos:
            return 0, 0, []

        tip = wallet.get_tip_height()
        depths = [max(0, tip - int(u['height']) + 1) if int(u['height']) > 0 else 0 for u in utxos]
        return sum(int(u['value']) for u in utxos), min(depths), utxos






    ############################################################
    # _deposit_still_backs
    ############################################################
    #
    # Just before a payout is built: are the coins it pays for
    # still on the deposit address, confirmed, as the rate lock
    # counted them — every one of them (an order locked before
    # the coins were tracked: as much as it counted)? A deposit
    # double-spent or reorganised away while the order waited
    # (a retry) sends the order back as far as it has to go -
    # to counting confirmations again when coins remain, to
    # awaiting its deposit when none do - and nothing is paid.
    #
    # Used by:
    #   - _send_payout (above)
    ############################################################

    def _deposit_still_backs(self, order: dict) -> bool:
        wallet = self.service.wallet_for_asset(order['from_asset'])
        utxos = wallet.get_unspent(order['deposit_scripthash'])
        confirmed = [u for u in utxos if int(u['height']) > 0]

        if order['paid_coins'] is not None:
            backed = set(json.loads(order['paid_coins'])) <= {self._outpoint(u) for u in confirmed}
        else:
            backed = sum(int(u['value']) for u in confirmed) >= int(round(order['received_amount'] * COIN))
        if backed:
            return True

        logger.warning('Order %s: its locked deposit is no longer on chain -> not paying', order['id'])
        received_sat = sum(int(u['value']) for u in utxos)
        if received_sat <= 0:
            self._send_back_to_awaiting_deposit(order)
        else:
            self.service.update_order(order['id'], {
                'status': 'awaiting_confirmations',
                'confirm_count': 0,
                'received_amount': received_sat / COIN,
                'locked_rate': None,
                'to_amount': order['from_amount'] * order['rate'],
                'paid_coins': None,
            })
        return False






    ############################################################
    # _payout_target
    ############################################################
    #
    # How deep a payout must confirm: as deep as its receiving
    # chain asks of a deposit (at least one confirmation).
    #
    # Used by:
    #   - _finish_pending_payout (above)
    ############################################################

    def _payout_target(self, order: dict) -> int:
        chain = self.service.chains[self.service.network_key(order['to_asset'])]
        return chain.confirm_target or 1






    ############################################################
    # _send_back_to_awaiting_deposit
    ############################################################
    #
    # The deposit is gone: the order waits for one again as if
    # the student had not paid yet - nothing received, no
    # deposit transaction, no locked rate or coins paid for,
    # the quote it was created with.
    #
    # Used by:
    #   - _check_confirmations, _lock_exchange_rate,
    #     _deposit_still_backs (above)
    ############################################################

    def _send_back_to_awaiting_deposit(self, order: dict):
        self.service.update_order(order['id'], {
            'status': 'awaiting_deposit',
            'tx_deposit_id': None,
            'confirm_count': 0,
            'received_amount': 0,
            'locked_rate': None,
            'to_amount': order['from_amount'] * order['rate'],
            'paid_coins': None,
        })






    ############################################################
    # _worth_sending_back
    ############################################################
    #
    # Whether the coins an order's payout paid for are worth a
    # refund: more than dust left of them once a one-output
    # spend of them has paid its fee.
    #
    # Used by:
    #   - _send_payout (above) — a payout below the dust limit
    ############################################################

    def _worth_sending_back(self, order: dict) -> bool:
        coins = len(json.loads(order['paid_coins'])) if order['paid_coins'] else 1
        received_sat = int(round(order['received_amount'] * COIN))
        return received_sat - spend_fee_sat(coins, 1, self.service.fee_rate) > DUST_LIMIT_SAT






    ############################################################
    # _start_refund
    ############################################################
    #
    # The order cannot go through: none of its coins is
    # exchanged any more (paid_coins cleared), so every coin on
    # its address goes back where it came from — _refund_order
    # takes it from here — and the reason is kept for the order
    # page.
    #
    # Used by:
    #   - _send_payout (above) — a reserve that cannot cover
    #     the payout, a payout below the dust limit
    ############################################################

    def _start_refund(self, order: dict, reason: str):
        self.service.update_order(order['id'], {'status': 'refunding', 'error': reason, 'paid_coins': None})






    ############################################################
    # _refund_order
    ############################################################
    #
    # refunding: follows the refunds already sent and sends back
    # whatever coin on the address is not on its way yet. Once
    # nothing is on its way back and nothing is left that could
    # be — or is still to confirm, so it can be — the order is
    # refunded; failed when not a single coin could be sent
    # back (too few of them, or no sender to find). A pass that
    # cannot be made — the chain's server not handing out the
    # deposits' transactions, an outage — fails nothing: it
    # raises, and the order is tried again REFUND_RETRY_MS
    # later rather than on every pass.
    #
    # Used by:
    #   - _loop (above) — refunding orders
    ############################################################

    def _refund_order(self, order: dict):
        # STEP 1: back off after a pass that could not be made
        # ====================================================
        if self.service.now() < self._refund_retry_due.get(order['id'], 0):
            return


        # STEP 2: follow the refunds sent, send back the rest
        # ===================================================
        wallet = self.service.wallet_for_asset(order['from_asset'])
        try:
            pending = self._follow_refunds(order, wallet)
            sent, waiting = self._send_back_unpaid(order, wallet)
        except Exception:
            self._refund_retry_due[order['id']] = self.service.now() + REFUND_RETRY_MS
            raise
        self._refund_retry_due.pop(order['id'], None)
        if pending or sent or waiting:
            return


        # STEP 3: nothing on its way back, nothing left to send
        # =====================================================
        refunded = bool(self.service.refunds_of(order['id']))
        logger.info('Order %s %s', order['id'], 'refunded' if refunded else 'could not be refunded -> failed')
        self.service.update_order(order['id'], {'status': 'refunded' if refunded else 'failed'})






    ############################################################
    # _follow_refunds
    ############################################################
    #
    # Follows an order's refunds that have not confirmed yet,
    # through the history of the deposit address they spend
    # from: one as deep as a deposit must be is confirmed; one
    # the history does not hold at all is broadcast again — the
    # very same transaction, so it can never refund twice; one
    # the chain refuses for good (its coins spent by something
    # else, a deposit double-spent away) is dropped, the coins
    # still there free to be sent back anew. Answers whether a
    # refund is still on its way.
    #
    # Used by:
    #   - _refund_order (above), _watch_late_coins (below)
    ############################################################

    def _follow_refunds(self, order: dict, wallet: ExchangeWallet) -> bool:
        pending = False
        target = order['confirm_target'] or 1

        for refund in self.service.refunds_of(order['id']):
            if refund['state'] == 'confirmed':
                continue

            confs = wallet.confirmations(refund['txid'], order['deposit_scripthash'])
            if confs is not None:
                if confs >= target:
                    logger.info('Refund for %s confirmed (%s/%s): %s', order['id'], confs, target, refund['txid'])
                    self.service.confirm_refund(order['id'], refund['txid'])
                else:
                    pending = True
                continue

            # Nowhere to be seen: out again, the very same transaction -
            # classified by message text as a lost payout is
            try:
                wallet.broadcast(refund['raw'])
                pending = True
            except Exception as e:
                message = str(e).lower()
                if 'already' in message or 'duplicate' in message:
                    pending = True
                elif 'missingorspent' in message or 'conflict' in message or 'bad-txns' in message:
                    logger.warning('Refund %s of order %s conflicted - dropped', refund['txid'], order['id'])
                    self.service.drop_refund(order['id'], refund['txid'])
                else:
                    raise

        return pending






    ############################################################
    # _send_back_unpaid
    ############################################################
    #
    # Sends the coins on an order's address that nothing pays
    # for back where they came from: every coin but those its
    # payout pays for and those a refund already holds. Only
    # confirmed coins go — one still in the mempool could yet
    # be replaced — each to the script that paid its
    # transaction's first input, all of them in one refund that
    # is persisted before it is broadcast. Coins with no sender
    # to find, or too few to be worth a refund, stay; a server
    # that does not hand out a coin's transactions raises, and
    # nothing goes out on that pass. Answers whether a refund
    # went out, and whether coins are still waiting to
    # confirm.
    #
    # An order completed before its coins were tracked has all
    # of them paid for: it sends nothing back.
    #
    # Used by:
    #   - _refund_order (above), _watch_late_coins (below)
    ############################################################

    def _send_back_unpaid(self, order: dict, wallet: ExchangeWallet):
        # STEP 1: the coins no payout pays for and no refund holds
        # ========================================================
        if order['status'] == 'completed' and order['paid_coins'] is None:
            return False, False

        taken = set(json.loads(order['paid_coins'] or '[]'))
        for refund in self.service.refunds_of(order['id']):
            taken.update(refund['coins'])
        coins = [coin for coin in wallet.get_unspent(order['deposit_scripthash']) if self._outpoint(coin) not in taken]


        # STEP 2: the confirmed ones, each with where it goes back to
        # ===========================================================
        confirmed = [coin for coin in coins if int(coin['height']) > 0]
        waiting = len(confirmed) < len(coins)

        refundable = []
        for coin in confirmed:
            refund_to = self._sender_of(wallet, coin['tx_hash'])
            if refund_to is not None:
                refundable.append(dict(coin, refund_to=refund_to))


        # STEP 3: sign, persist, broadcast
        # ================================
        refund = wallet.build_refund_tx(wallet.derive(order['deposit_index']), refundable, self.service.fee_rate)
        if refund is None:
            return False, waiting

        txid, raw_hex, recipients, spent = refund
        self.service.add_refund(order['id'], txid, raw_hex, [self._outpoint(coin) for coin in spent], [
            {'address': wallet.address_of(refund_to), 'amount': amount / COIN} for refund_to, amount in recipients
        ])
        wallet.broadcast(raw_hex)
        logger.info('Refund for %s broadcast: %s (%s %s)',
                    order['id'], txid, sum(amount for _refund_to, amount in recipients) / COIN, order['from_asset'])
        return True, waiting






    ############################################################
    # _sender_of
    ############################################################
    #
    # The script a deposit transaction's coins go back to (see
    # ExchangeWallet.sender_of), asked of the chain once and
    # remembered — the answer that there is none included, as
    # a transaction never changes its inputs. A lookup the
    # server could not answer raises, leaving nothing behind,
    # so a later pass asks again.
    #
    # Used by:
    #   - _send_back_unpaid (above)
    ############################################################

    def _sender_of(self, wallet: ExchangeWallet, tx_hash: str):
        if tx_hash not in self._senders:
            self._senders[tx_hash] = wallet.sender_of(tx_hash)
        return self._senders[tx_hash]






    ############################################################
    # _watch_late_coins
    ############################################################
    #
    # The addresses no step follows any more are still looked
    # at, every LATE_DEPOSIT_CHECK_MS for LATE_DEPOSIT_WINDOW_MS
    # after the order's deadline. An order expires on a positive
    # "nothing has arrived" answer at its deadline, but coins
    # can still come afterwards — a student paying late, or a
    # deposit a reorganisation took away and the chain then
    # mined after all: they take the expired order back into the
    # lifecycle (awaiting_confirmations, its rate locked once
    # they are deep enough). On an order that is done —
    # completed, failed or refunded — late coins are not
    # exchanged: its refunds are followed and the coins nothing
    # pays for are sent back — a failed order that sends some
    # is refunding again, as failed means not one coin went
    # back. Either way nothing is stranded on an address nobody
    # watches. A completed order's deposit is looked at as well
    # (see _follow_paid_deposit): one the chain took back
    # reverses the order, which then sends nothing back — the
    # exchange paid for its deposit once already.
    #
    # Used by:
    #   - _loop (above) — every pass
    ############################################################

    def _watch_late_coins(self):
        # STEP 1: once every LATE_DEPOSIT_CHECK_MS at most
        # ================================================
        now = self.service.now()
        if now < self._late_check_due:
            return
        self._late_check_due = now + LATE_DEPOSIT_CHECK_MS


        # STEP 2: the orders no step follows whose deadline passed
        # within the window
        # ========================================================
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM orders WHERE status IN ('expired', 'completed', 'reversed', 'failed', 'refunded') "
                "AND expires_at > ?",
                [now - LATE_DEPOSIT_WINDOW_MS],
            )
            orders = [dict(row) for row in cur.fetchall()]


        # STEP 3: coins on an expired order's address take it back
        # up; an order that is done sends back what it does not pay
        # for — unless the chain took back the deposit it paid for
        # =========================================================
        for order in orders:
            try:
                wallet = self.service.wallet_for_asset(order['from_asset'])
                if order['status'] == 'expired':
                    if wallet.get_received_sat(order['deposit_scripthash']) > 0:
                        logger.info('Late deposit on expired order %s -> back in the lifecycle', order['id'])
                        self._check_deposit(order)
                else:
                    if order['status'] in ('completed', 'reversed'):
                        order = dict(order, status=self._follow_paid_deposit(order, wallet))
                    self._follow_refunds(order, wallet)

                    # Whatever reaches a reversed order's address stays there for
                    # the operator: most likely it is the replacement of the very
                    # deposit the exchange already paid for
                    if order['status'] != 'reversed':
                        self._send_back_unpaid(order, wallet)

                    # Late coins of a failed order, or its own: an order failed
                    # while a chain server's refusal to hand out its deposit
                    # still read as "no sender" sends them once it does
                    if order['status'] == 'failed' and self.service.refunds_of(order['id']):
                        logger.info('Failed order %s sent coins back after all -> refunding', order['id'])
                        self.service.update_order(order['id'], {'status': 'refunding'})
            except Exception as e:
                logger.error('Late coin check failed for %s: %s', order['id'], e)






    ############################################################
    # _follow_paid_deposit
    ############################################################
    #
    # After the payout: are the deposit transactions it paid
    # for still in the chain? A reorganisation can take one back
    # out once the exchange has paid for it — double-spent, or
    # never mined again — and those coins are lost to the
    # exchange: the order is reversed, logged as an error and
    # shown as such, the deposit transaction it names one the
    # chain took back. A deposit back in the mempool is not
    # reversed (it can still be mined again); a reversed
    # order's deposit the chain holds again, confirmed, makes
    # it completed again. The deposit transactions are those of
    # the coins the payout paid for (an order locked before
    # coins were tracked: the one seen first), looked up in the
    # address history, which keeps them after the sweep spent
    # their coins. Answers the order's status now.
    #
    # Used by:
    #   - _watch_late_coins (above) — completed and reversed
    #     orders, for a day after their deadline
    ############################################################

    def _follow_paid_deposit(self, order: dict, wallet: ExchangeWallet) -> str:
        if order['paid_coins'] is not None:
            paid = {outpoint.rsplit(':', 1)[0] for outpoint in json.loads(order['paid_coins'])}
        else:
            paid = {order['tx_deposit_id']} if order['tx_deposit_id'] else set()
        heights = {entry['tx_hash']: int(entry['height']) for entry in wallet.get_history(order['deposit_scripthash'])}
        gone = sorted(paid - heights.keys())

        if order['status'] == 'completed' and gone:
            logger.error('Order %s: deposit %s left the chain after its payout -> reversed', order['id'], ', '.join(gone))

            # The page marks the deposit transaction the order names as no
            # longer in the main chain: it must be one that left it
            updates = {'status': 'reversed'}
            if order['tx_deposit_id'] not in gone:
                updates['tx_deposit_id'] = gone[0]
            self.service.update_order(order['id'], updates)
            return 'reversed'

        if order['status'] == 'reversed' and all(heights.get(txid, 0) > 0 for txid in paid):
            logger.warning('Order %s: its deposit is back in the chain -> completed', order['id'])
            self.service.update_order(order['id'], {'status': 'completed'})
            return 'completed'

        return order['status']






    ############################################################
    # _sweep_finished_orders
    ############################################################
    #
    # Deposits arrive on per-order addresses, but payouts spend
    # from the reserve - without this step the reserves would
    # only ever drain while finished orders sat on their coins.
    # So once an order completes with coins on its deposit
    # address, the coins its payout paid for are swept to this
    # chain's reserve. Nothing else is: the coins of an order
    # that failed or was refunded, and every coin that arrived
    # after the rate lock, are the student's. A sweep that fails
    # leaves the order unswept, to be tried again on a later
    # pass.
    #
    # Used by:
    #   - _loop (above) — every pass
    ############################################################

    def _sweep_finished_orders(self):
        with get_db_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM orders WHERE sweep_state IS NULL "
                "AND status = 'completed' AND received_amount > 0"
            )
            orders = [dict(row) for row in cur.fetchall()]

        for order in orders:
            try:
                self._sweep_deposit(order)
            except Exception as e:
                # Transient (Electrum down, mempool conflict, ...): the order
                # stays sweep_state NULL and is retried on a later tick.
                logger.error('Sweep failed for %s: %s', order['id'], e)






    ############################################################
    # _sweep_deposit
    ############################################################
    #
    # Sweeps one completed order's paid-for coins and records
    # the outcome in sweep_state. Idempotency comes from the
    # chain itself: a sweep spends ALL of the coins the payout
    # paid for, so once one broadcast succeeds none of them is
    # left and the order is simply marked done - a second,
    # conflicting sweep can never confirm. Coins emptied away
    # by a reorganisation instead are told apart by the
    # address's history and marked 'missing'. An order locked
    # before its coins were tracked sweeps everything on the
    # address.
    #
    # Used by:
    #   - _sweep_finished_orders (above)
    ############################################################

    def _sweep_deposit(self, order: dict):
        # STEP 1: a transaction sweeping the coins the payout paid
        # for, those still there
        # ========================================================
        wallet = self.service.wallet_for_asset(order['from_asset'])
        deposit = wallet.derive(order['deposit_index'])

        coins = None
        if order['paid_coins'] is not None:
            paid = set(json.loads(order['paid_coins']))
            coins = [coin for coin in wallet.get_unspent(deposit.scripthash) if self._outpoint(coin) in paid]

        sweep = wallet.build_sweep_tx(deposit, self.service.fee_rate, coins)


        # STEP 2: nothing worth sweeping — record why
        # ===========================================
        if sweep is None:
            # Nothing (or only dust) left of those coins. "Nothing" also
            # covers a sweep that was broadcast just before a crash - the
            # UTXOs are gone, so the work is done either way - but only while
            # the address history still lists the deposit. When the recorded
            # deposit transaction has left the history too, a reorganisation
            # or a double-spend took the coins after the payout went out:
            # that is recorded as 'missing' and reported, never as a sweep.
            if coins if coins is not None else wallet.get_unspent(deposit.scripthash):
                state = 'dust'
            elif order['tx_deposit_id'] and order['tx_deposit_id'] not in {
                    h['tx_hash'] for h in wallet.get_history(deposit.scripthash)}:
                logger.error('Deposit %s of order %s is gone from the chain after its payout - nothing to sweep',
                             order['tx_deposit_id'], order['id'])
                state = 'missing'
            else:
                state = 'swept'
            self.service.update_order(order['id'], {'sweep_state': state})
            return


        # STEP 3: broadcast it and record the sweep
        # =========================================
        txid, raw_hex, amount_sat = sweep
        wallet.broadcast(raw_hex)
        logger.info('Swept %s %s from order %s to reserve: %s',
                    amount_sat / COIN, order['from_asset'], order['id'], txid)
        self.service.update_order(order['id'], {'sweep_state': 'swept', 'tx_sweep_id': txid})






    ############################################################
    # _outpoint
    ############################################################
    #
    # The name of one coin: the transaction that made it and the
    # position of its output there, as "txid:vout" — how
    # paid_coins and the refunds name the coins they hold.
    #
    # Used by:
    #   - _lock_exchange_rate, _deposit_still_backs,
    #     _send_back_unpaid, _sweep_deposit (above)
    ############################################################

    @staticmethod
    def _outpoint(coin: dict) -> str:
        return f"{coin['tx_hash']}:{coin['tx_pos']}"
