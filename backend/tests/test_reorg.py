############################################################
#  [*] Reorganisation tests — when the chain changes its mind
#
#  A deposit, a top-up or a payout can disappear or move after
#  the worker has seen it: its block orphaned (the transaction
#  falls back into the mempool), the transaction double-spent,
#  replaced by a fee bump or evicted, mined again in another
#  block, or read from an Electrum server that lags behind.
#  These tests script such timelines on the FakeWallets and
#  follow an order through them, stage by stage:
#
#    - while confirming: confirmations follow the block the
#      deposit is in now, a vanished deposit sends the order
#      back to awaiting it with nothing recorded as received,
#      and a deposit that returns — the same transaction, or a
#      fee bump under a new id — moves it forward again; a
#      replacement for less is what gets paid
#    - around the rate lock: only coins confirmed as deep as
#      the target are paid for — a deposit an orphaned block
#      put back into the mempool, or a top-up still waiting
#      there, sends the order back to counting confirmations
#    - after the lock: a deposit that vanished, fell back into
#      the mempool, or was replaced by another coin, while the
#      order waited for its payout is never paid out
#    - the payout itself: the order completes only once it has
#      confirmed; one the mempool lost is broadcast again,
#      never rebuilt, one seen out after all clears the failure
#      to broadcast it again, and one already out is followed
#      to the end whatever happens to the deposit
#    - an order sent back after its deadline expires, and the
#      coins that come back afterwards are taken up again
#    - after completion: a deposit the chain took back is
#      recorded as missing and reported, never as swept, and
#      reverses the order — completed again once the chain
#      holds it again, a deposit back in the mempool reversing
#      nothing, a reversed order sending nothing back
#
#  (How the wallet picks reserve coins for a payout is tested
#  in test_wallet.py.)
############################################################


from app.wallet import COIN
from app.config import RATE_KNF_TO_LTC
from app.worker import PAYOUT_RETRY_MS

from tests.base import ExchangeTestCase


# The deposit transaction the student broadcasts first
DEPOSIT = 'deposit-tx'

# The payout transaction the tLTC4 FakeWallet builds
PAYOUT = 'payout-txid'

# What a 10 KNF deposit is paid, in tLTC4 satoshis
TEN_KNF_PAID = ('tltc1qstudent', int(round(10 * RATE_KNF_TO_LTC * COIN)))








############################################################
# ReorgTestCase
############################################################
#
# The stages a reorganisation can hit, each reached through
# the worker's own steps (a 10 KNF -> tLTC4 order unless told
# otherwise): the deposit seen, confirmed, the rate locked,
# the payout broadcast, the order completed.
#
# Used by:
#   - every test class below
############################################################

class ReorgTestCase(ExchangeTestCase):

    def seen(self, amount_sat=10 * COIN):
        # The deposit has just been seen, in the mempool
        order = self.create_order()
        self.wallet_of(order).receive(order['deposit_scripthash'], DEPOSIT, amount_sat)
        self.worker._check_deposit(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')
        return self.reload(order)

    def confirmed(self, amount_sat=10 * COIN):
        # Mined at 100 with the tip at 101: two confirmations, the target
        order = self.seen(amount_sat)
        self.knf_wallet.mine(DEPOSIT, 100)
        self.knf_wallet.tip_height = 101
        self.worker._check_confirmations(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'exchanging')
        return self.reload(order)

    def locked(self, amount_sat=10 * COIN):
        # The rate is locked and the payout is due
        order = self.confirmed(amount_sat)
        self.worker._lock_exchange_rate(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'sending')
        return self.reload(order)

    def payout_broadcast(self):
        # The payout went out and waits, unconfirmed, on the tLTC4 chain
        order = self.locked()
        self.assertEqual(self.send_payout(order)['tx_send_id'], PAYOUT)
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])
        return self.reload(order)

    def completed(self):
        # The payout confirmed as deep as the tLTC4 chain asks
        order = self.payout_broadcast()
        self.ltc_wallet.bury(PAYOUT)
        self.assertEqual(self.send_payout(order)['status'], 'completed')
        return self.reload(order)

    def check_confirmations(self, order):
        self.worker._check_confirmations(self.reload(order))
        return self.reload(order)

    def send_payout(self, order):
        self.worker._send_payout(self.reload(order))
        return self.reload(order)








############################################################
# TestWhileConfirming
############################################################
#
# The deposit's block orphaned, the deposit mined again in
# another block, or read from a server lagging behind, while
# the order counts its confirmations.
############################################################

class TestWhileConfirming(ReorgTestCase):

    def test_confirmations_fall_back_when_the_block_is_orphaned(self):
        order = self.seen()
        self.knf_wallet.mine(DEPOSIT, 100)
        self.knf_wallet.tip_height = 100
        self.assertEqual(self.check_confirmations(order)['confirm_count'], 1)

        self.knf_wallet.orphan(DEPOSIT)
        updated = self.check_confirmations(order)

        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['confirm_count'], 0)
        self.assertEqual(updated['tx_deposit_id'], DEPOSIT)

    def test_confirmations_count_from_the_block_the_deposit_is_in_now(self):
        # Mined at 100; the new chain carries it in block 101 instead, so
        # at tip 101 it has one confirmation, not the two it would have had
        order = self.seen()
        self.knf_wallet.mine(DEPOSIT, 100)
        self.knf_wallet.tip_height = 100
        self.check_confirmations(order)

        self.knf_wallet.mine(DEPOSIT, 101)
        self.knf_wallet.tip_height = 101
        updated = self.check_confirmations(order)

        self.assertEqual(updated['confirm_count'], 1)
        self.assertEqual(updated['status'], 'awaiting_confirmations')

    def test_a_server_lagging_behind_the_deposit_block_counts_none(self):
        order = self.seen()
        self.knf_wallet.mine(DEPOSIT, 100)
        self.knf_wallet.tip_height = 98

        updated = self.check_confirmations(order)

        self.assertEqual(updated['confirm_count'], 0)
        self.assertEqual(updated['status'], 'awaiting_confirmations')

    def test_a_deposit_waiting_on_unconfirmed_parents_counts_none(self):
        # Electrum reports such a mempool transaction at height -1
        order = self.seen()
        self.knf_wallet.mine(DEPOSIT, -1)

        self.assertEqual(self.check_confirmations(order)['confirm_count'], 0)

    def test_an_orphaned_deposit_that_confirms_again_moves_on(self):
        order = self.seen()
        self.knf_wallet.mine(DEPOSIT, 100)
        self.knf_wallet.tip_height = 100
        self.check_confirmations(order)
        self.knf_wallet.orphan(DEPOSIT)
        self.check_confirmations(order)

        self.knf_wallet.mine(DEPOSIT, 103)
        self.knf_wallet.tip_height = 104
        updated = self.check_confirmations(order)

        self.assertEqual(updated['status'], 'exchanging')
        self.assertEqual(updated['confirm_count'], 2)

    def test_a_top_up_that_vanishes_takes_the_received_amount_back_down(self):
        order = self.seen(10 * COIN)
        self.knf_wallet.receive(order['deposit_scripthash'], 'top-up-tx', 5 * COIN)
        self.assertEqual(self.check_confirmations(order)['received_amount'], 15.0)

        self.knf_wallet.drop('top-up-tx')

        self.assertEqual(self.check_confirmations(order)['received_amount'], 10.0)

    def test_an_empty_answer_never_wipes_the_recorded_amount(self):
        # The history still lists the deposit but the UTXO answer comes back
        # empty — a server in the middle of a reorganisation
        order = self.seen(10 * COIN)
        self.knf_wallet.unspent[order['deposit_scripthash']] = []

        updated = self.check_confirmations(order)

        self.assertEqual(updated['received_amount'], 10.0)
        self.assertEqual(updated['status'], 'awaiting_confirmations')








############################################################
# TestDepositVanishedWhileConfirming
############################################################
#
# The deposit double-spent, replaced or evicted while
# confirming: the order goes back to awaiting it, and a
# deposit that returns moves it on again.
############################################################

class TestDepositVanishedWhileConfirming(ReorgTestCase):

    def test_a_double_spent_deposit_sends_the_order_back_to_awaiting_it(self):
        order = self.seen()
        self.knf_wallet.drop(DEPOSIT)

        updated = self.check_confirmations(order)

        self.assertEqual(updated['status'], 'awaiting_deposit')
        self.assertIsNone(updated['tx_deposit_id'])
        self.assertEqual(updated['confirm_count'], 0)

    def test_sending_the_order_back_clears_the_received_amount(self):
        # The coins are gone, so nothing reads as received any more
        order = self.seen()
        self.knf_wallet.drop(DEPOSIT)

        self.assertEqual(self.check_confirmations(order)['received_amount'], 0)

    def test_the_order_moves_forward_again_when_the_deposit_returns(self):
        # The student rebroadcasts the same transaction
        order = self.seen()
        self.knf_wallet.drop(DEPOSIT)
        self.check_confirmations(order)

        self.knf_wallet.receive(order['deposit_scripthash'], DEPOSIT, 10 * COIN)
        self.worker._check_deposit(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['tx_deposit_id'], DEPOSIT)
        self.assertEqual(updated['received_amount'], 10.0)

    def test_a_fee_bumped_deposit_is_followed_under_its_new_id(self):
        # The deposit is replaced (RBF) by a copy paying a higher fee
        order = self.seen()
        self.knf_wallet.drop(DEPOSIT)
        self.knf_wallet.receive(order['deposit_scripthash'], 'bumped-tx', 10 * COIN)

        self.assertEqual(self.check_confirmations(order)['status'], 'awaiting_deposit')
        self.worker._check_deposit(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['tx_deposit_id'], 'bumped-tx')

    def test_a_replacement_for_less_is_what_gets_paid(self):
        # The replacement pays 6 KNF instead of 10: the payout follows the
        # coins that are really there
        order = self.seen(10 * COIN)
        self.knf_wallet.drop(DEPOSIT)
        self.knf_wallet.receive(order['deposit_scripthash'], 'smaller-tx', 6 * COIN)
        self.check_confirmations(order)
        self.worker._check_deposit(self.reload(order))

        self.knf_wallet.mine('smaller-tx', 100)
        self.knf_wallet.tip_height = 101
        self.assertEqual(self.check_confirmations(order)['status'], 'exchanging')
        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['received_amount'], 6.0)
        self.assertAlmostEqual(updated['to_amount'], 6.0 * RATE_KNF_TO_LTC)








############################################################
# TestAroundTheRateLock
############################################################
#
# What the rate lock pays for: only coins confirmed as deep
# as the target.
############################################################

class TestAroundTheRateLock(ReorgTestCase):

    def test_the_way_back_from_the_lock_clears_the_received_amount_too(self):
        order = self.confirmed()
        self.knf_wallet.drop(DEPOSIT)

        self.worker._lock_exchange_rate(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_deposit')
        self.assertEqual(updated['received_amount'], 0)

    def test_a_deposit_back_in_the_mempool_is_not_locked(self):
        # Its block was orphaned between the count and the lock: the order
        # counts confirmations again
        order = self.confirmed()
        self.knf_wallet.orphan(DEPOSIT)

        self.worker._lock_exchange_rate(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['confirm_count'], 0)
        self.assertIsNone(updated['locked_rate'])

    def test_a_deposit_mined_again_after_the_orphaning_is_locked(self):
        order = self.confirmed()
        self.knf_wallet.orphan(DEPOSIT)
        self.worker._lock_exchange_rate(order)

        self.knf_wallet.mine(DEPOSIT, 102)
        self.knf_wallet.tip_height = 103
        self.assertEqual(self.check_confirmations(order)['status'], 'exchanging')
        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['locked_rate'], RATE_KNF_TO_LTC)

    def test_an_unconfirmed_top_up_holds_the_lock_until_it_confirms(self):
        # A second payment still in the mempool would be paid for as well,
        # so the lock waits for it to be as deep as the deposit
        order = self.confirmed(1 * COIN)
        self.knf_wallet.receive(order['deposit_scripthash'], 'top-up-tx', 2 * COIN)

        self.worker._lock_exchange_rate(self.reload(order))
        held = self.reload(order)
        self.assertEqual(held['status'], 'awaiting_confirmations')
        self.assertEqual(held['received_amount'], 3.0)
        self.assertIsNone(held['locked_rate'])

        self.knf_wallet.mine('top-up-tx', 102)
        self.knf_wallet.tip_height = 103
        self.assertEqual(self.check_confirmations(order)['status'], 'exchanging')
        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['received_amount'], 3.0)
        self.assertAlmostEqual(updated['to_amount'], 3.0 * RATE_KNF_TO_LTC)

    def test_only_confirmed_coins_are_paid_for(self):
        # The top-up never confirms - it is double-spent away - so only the
        # deposit that did is paid for
        order = self.confirmed(1 * COIN)
        self.knf_wallet.receive(order['deposit_scripthash'], 'top-up-tx', 999 * COIN)
        self.worker._lock_exchange_rate(self.reload(order))

        self.knf_wallet.drop('top-up-tx')
        self.assertEqual(self.check_confirmations(order)['status'], 'exchanging')
        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['received_amount'], 1.0)
        self.assertAlmostEqual(updated['to_amount'], 1.0 * RATE_KNF_TO_LTC)

    def test_a_top_up_confirmed_with_the_deposit_is_paid_for(self):
        # A second payment that confirmed too is the student's as well
        order = self.confirmed(1 * COIN)
        self.knf_wallet.receive(order['deposit_scripthash'], 'top-up-tx', 2 * COIN, height=100)

        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['received_amount'], 3.0)
        self.assertAlmostEqual(updated['to_amount'], 3.0 * RATE_KNF_TO_LTC)








############################################################
# TestAfterTheRateLock
############################################################
#
# A deposit that vanished, fell back into the mempool or was
# replaced by another coin while the order waited for its
# payout.
############################################################

class TestAfterTheRateLock(ReorgTestCase):

    def test_no_payout_for_a_deposit_that_vanished(self):
        # Double-spent away while the order waited in "sending" (a retry):
        # it goes back to awaiting its deposit
        order = self.locked()
        self.knf_wallet.drop(DEPOSIT)

        updated = self.send_payout(order)

        self.assertEqual(updated['status'], 'awaiting_deposit')
        self.assertEqual(updated['received_amount'], 0)
        self.assertIsNone(updated['locked_rate'])
        self.assertEqual(self.ltc_wallet.payout_requests, [])
        self.assertEqual(self.ltc_wallet.broadcasts, [])

    def test_no_payout_for_a_deposit_back_in_the_mempool(self):
        # Its block was orphaned while the order waited: it counts
        # confirmations again, and is paid once the deposit is deep again
        order = self.locked()
        self.knf_wallet.orphan(DEPOSIT)

        updated = self.send_payout(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['received_amount'], 10.0)
        self.assertIsNone(updated['locked_rate'])
        self.assertEqual(self.ltc_wallet.payout_requests, [])

        self.knf_wallet.mine(DEPOSIT, 102)
        self.knf_wallet.tip_height = 103
        for _ in range(3):
            self.tick()

        self.assertEqual(self.ltc_wallet.payout_requests, [TEN_KNF_PAID])

    def test_no_payout_for_a_deposit_replaced_by_another_coin(self):
        # The deposit was double-spent and another payment of the same size
        # arrived: the payout pays for the coins the lock counted, not for an
        # amount, so the order counts its coins again
        order = self.locked()
        self.knf_wallet.drop(DEPOSIT)
        self.knf_wallet.receive(order['deposit_scripthash'], 'other-tx', 10 * COIN, height=101)

        updated = self.send_payout(order)

        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertIsNone(updated['paid_coins'])
        self.assertEqual(self.ltc_wallet.payout_requests, [])








############################################################
# TestAfterThePayoutWentOut
############################################################
#
# The payout's own reorganisations: the order completes only
# once it has confirmed, one the mempool lost goes out again
# unchanged, and one already out is followed to the end.
############################################################

class TestAfterThePayoutWentOut(ReorgTestCase):

    def test_the_order_completes_only_once_the_payout_has_confirmed(self):
        order = self.payout_broadcast()

        self.ltc_wallet.bury(PAYOUT, confirmations=1)
        self.assertEqual(self.send_payout(order)['status'], 'sending')

        self.ltc_wallet.bury(PAYOUT, confirmations=2)
        self.assertEqual(self.send_payout(order)['status'], 'completed')

    def test_a_payout_the_mempool_lost_is_broadcast_again_never_rebuilt(self):
        # The very same transaction goes out again - same txid, so the
        # student can never be paid twice
        order = self.payout_broadcast()
        self.ltc_wallet.drop(PAYOUT)

        updated = self.send_payout(order)

        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex', 'payout-raw-hex'])
        self.assertEqual(self.ltc_wallet.payout_requests, [TEN_KNF_PAID])

        self.ltc_wallet.bury(PAYOUT)
        self.assertEqual(self.send_payout(order)['status'], 'completed')

    def test_a_payout_whose_block_was_orphaned_waits_to_confirm_again(self):
        order = self.payout_broadcast()
        self.ltc_wallet.bury(PAYOUT, confirmations=1)
        self.ltc_wallet.orphan(PAYOUT)

        updated = self.send_payout(order)

        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['tx_send_id'], PAYOUT)
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])   # still in the mempool

    def test_a_payout_seen_out_after_all_clears_the_failure_to_broadcast_it_again(self):
        # The pages show a payout out as done only with no failure on record
        order = self.payout_broadcast()
        self.ltc_wallet.drop(PAYOUT)
        self.ltc_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')
        self.assertEqual(self.send_payout(order)['error'], 'Electrum 127.0.0.1:1 unreachable: timed out')

        self.ltc_wallet.broadcast_error = None
        self.ltc_wallet.bury(PAYOUT, confirmations=1)
        self.at(self.service.now() + PAYOUT_RETRY_MS)
        updated = self.send_payout(order)

        self.assertEqual((updated['status'], updated['error']), ('sending', None))
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])

    def test_a_payout_already_out_is_followed_whatever_happens_to_the_deposit(self):
        # A broadcast payout cannot be called back: it is followed to its
        # confirmation, never built a second time - and the order then says
        # what became of its deposit
        order = self.payout_broadcast()
        self.knf_wallet.drop(DEPOSIT)
        self.ltc_wallet.bury(PAYOUT)

        self.assertEqual(self.send_payout(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.payout_requests, [TEN_KNF_PAID])

        with self.assertLogs('exchange.worker', 'ERROR'):
            self.worker._watch_late_coins()
        self.assertEqual(self.reload(order)['status'], 'reversed')








############################################################
# TestSentBackAfterTheDeadline
############################################################
#
# An order sent back after its 30-minute deadline expires
# unless the deposit is back — and coins that return later
# still take it up.
############################################################

class TestSentBackAfterTheDeadline(ReorgTestCase):

    def sent_back_after_the_deadline(self):
        # The deposit vanished, the order went back to awaiting it — and
        # its 30-minute deadline has passed in the meantime
        order = self.seen()
        self.knf_wallet.drop(DEPOSIT)
        self.check_confirmations(order)
        self.at(order['expires_at'] + 60 * 1000)
        return self.reload(order)

    def test_a_deposit_back_in_the_mempool_still_counts(self):
        # The chain is asked before the deadline is applied: the deposit is
        # back, so the deadline no longer matters
        order = self.sent_back_after_the_deadline()
        self.knf_wallet.receive(order['deposit_scripthash'], DEPOSIT, 10 * COIN)

        self.worker._check_deposit(order)

        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')

    def test_with_nothing_on_its_address_the_order_expires(self):
        order = self.sent_back_after_the_deadline()

        self.worker._check_deposit(order)

        self.assertEqual(self.reload(order)['status'], 'expired')

    def test_coins_that_come_back_after_the_expiry_are_taken_up_again(self):
        # The deposit is mined after all, a minute after the order expired
        order = self.sent_back_after_the_deadline()
        self.worker._check_deposit(order)
        self.assertEqual(self.reload(order)['status'], 'expired')

        self.knf_wallet.receive(order['deposit_scripthash'], DEPOSIT, 10 * COIN, height=105)
        self.knf_wallet.tip_height = 106
        self.tick()

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['tx_deposit_id'], DEPOSIT)
        self.assertEqual(updated['received_amount'], 10.0)

        for _ in range(3):
            self.tick()
        self.assertEqual(self.ltc_wallet.payout_requests, [TEN_KNF_PAID])








############################################################
# TestAfterCompletion
############################################################
#
# A deposit the chain took back after the payout: recorded
# as missing and reported, never as swept — and the order
# reversed for as long as the chain does not hold it again.
############################################################

class TestAfterCompletion(ReorgTestCase):

    def watch(self, order):
        # The late-coin watch's look at the order, due now
        self.worker._late_check_due = 0
        self.worker._watch_late_coins()
        return self.reload(order)

    def test_a_deposit_double_spent_after_the_payout_reverses_the_order(self):
        order = self.completed()
        self.knf_wallet.drop(DEPOSIT)

        with self.assertLogs('exchange.worker', 'ERROR') as logs:
            updated = self.watch(order)

        self.assertEqual(updated['status'], 'reversed')
        self.assertIn(f"Order {order['id']}: deposit {DEPOSIT} left the chain after its payout -> reversed",
                      '\n'.join(logs.output))

    def test_a_reversed_order_names_the_deposit_the_chain_took_back(self):
        # Two payments paid for, and the second one gone: that is the
        # deposit transaction the order names from now on
        order = self.seen()
        self.knf_wallet.receive(order['deposit_scripthash'], 'top-up-tx', 5 * COIN)
        for tx_hash in (DEPOSIT, 'top-up-tx'):
            self.knf_wallet.mine(tx_hash, 100)
        self.knf_wallet.tip_height = 101
        self.assertEqual(self.check_confirmations(order)['status'], 'exchanging')
        self.worker._lock_exchange_rate(self.reload(order))
        self.send_payout(order)
        self.ltc_wallet.bury(PAYOUT)
        self.assertEqual(self.send_payout(order)['status'], 'completed')
        self.knf_wallet.drop('top-up-tx')

        with self.assertLogs('exchange.worker', 'ERROR'):
            updated = self.watch(order)

        self.assertEqual((updated['status'], updated['tx_deposit_id']), ('reversed', 'top-up-tx'))

    def test_a_deposit_back_in_the_mempool_reverses_nothing_yet(self):
        # Its block orphaned, it can still be mined again
        order = self.completed()
        self.knf_wallet.orphan(DEPOSIT)

        self.assertEqual(self.watch(order)['status'], 'completed')

    def test_a_deposit_mined_again_in_another_block_keeps_the_order_completed(self):
        order = self.completed()
        self.knf_wallet.mine(DEPOSIT, 101)

        self.assertEqual(self.watch(order)['status'], 'completed')

    def test_the_order_is_completed_again_once_the_chain_holds_the_deposit_again(self):
        order = self.completed()
        self.knf_wallet.drop(DEPOSIT)
        with self.assertLogs('exchange.worker', 'ERROR'):
            self.assertEqual(self.watch(order)['status'], 'reversed')

        # Back in the mempool first: still reversed, until it is mined
        self.knf_wallet.receive(order['deposit_scripthash'], DEPOSIT, 10 * COIN)
        self.assertEqual(self.watch(order)['status'], 'reversed')

        self.knf_wallet.mine(DEPOSIT, 101)
        self.assertEqual(self.watch(order)['status'], 'completed')

    def test_a_reversed_order_sends_nothing_back(self):
        # Coins on its address now - most likely the deposit's replacement -
        # stay there: the exchange paid for that deposit once already
        order = self.completed()
        self.knf_wallet.drop(DEPOSIT)
        self.knf_wallet.receive(order['deposit_scripthash'], 'replacement-tx', 10 * COIN, height=101)

        with self.assertLogs('exchange.worker', 'ERROR'):
            self.assertEqual(self.watch(order)['status'], 'reversed')
        self.assertEqual(self.watch(order)['status'], 'reversed')

        self.assertEqual(self.knf_wallet.refunds_built, 0)
        self.assertEqual(self.reload(order)['refunds'], [])

    def test_a_deposit_gone_after_the_payout_is_recorded_as_missing_not_swept(self):
        order = self.completed()
        self.knf_wallet.drop(DEPOSIT)

        with self.assertLogs('exchange.worker', 'ERROR') as logs:
            self.worker._sweep_finished_orders()

        updated = self.reload(order)
        self.assertEqual(updated['sweep_state'], 'missing')
        self.assertIsNone(updated['tx_sweep_id'])
        self.assertIn(f"Deposit {DEPOSIT} of order {order['id']} is gone from the chain after its payout",
                      '\n'.join(logs.output))
