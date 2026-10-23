############################################################
#  [*] Worker tests — the order lifecycle state machine
#
#  The invariants that keep the exchange honest, each of which
#  has bitten (or nearly bitten) in production:
#
#    - deposits of ANY size advance the order; the payout is
#      always priced from what actually arrived on-chain, and
#      only once every coin of it is confirmed deep enough
#    - expiry only fires while nothing has been received, and
#      coins arriving on an expired order's address within a
#      day take it back into the lifecycle
#    - a signed payout is persisted before broadcasting, and a
#      crashed payout is finished, never rebuilt (no double pay)
#    - an order completes only once its payout has confirmed
#    - a payout that cannot be made — the reserve cannot cover
#      it, or it is below the dust limit — sends the order's
#      coins back (fails it, too few to send back), while one
#      that cannot get out yet retries
#    - completed orders are swept into the reserve exactly
#      once, with the coins their payout paid for and nothing
#      else
#
#  and around them: the deadline's exact edge, which deposit
#  transaction is tracked, confirmation targets, the rate in
#  force at the lock (and its inverse for LTC -> KNF) and the
#  coins it fixes, the payout's back-off, rounding and dust
#  edge, every outcome of rebroadcasting an interrupted payout,
#  sweeps on the right chain and their retries, and the daemon
#  thread's start and stop. (Reorganisations have their own
#  file, test_reorg.py; refunds test_refunds.py; whole orders
#  through the loop live in test_lifecycle.py.)
############################################################


import json
import threading
from unittest.mock import patch

from app.wallet import COIN, ReserveShortfall
from app.config import RATE_KNF_TO_LTC
from app.service import KNF, LTC

from tests.base import ExchangeTestCase


# Why a payout of 100 sat is not made, as the worker words it
DUST_100_SAT = "Received amount is too small to pay out (a payout of 0.000001 LTC Testnet is below the network's minimum of 0.00000547 LTC Testnet)"








############################################################
# TestCheckDeposit
############################################################
#
# awaiting_deposit: any deposit moves the order on, and the
# deadline is only applied once the chain has been asked.
############################################################

class TestCheckDeposit(ExchangeTestCase):

    def test_nothing_received_keeps_waiting(self):
        order = self.create_order()
        self.worker._check_deposit(order)
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

    def test_nothing_received_past_deadline_expires(self):
        order = self.create_order()
        self.service.update_order(order['id'], {'expires_at': self.service.now() - 1000})

        self.worker._check_deposit(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'expired')

    def test_any_deposit_advances_even_when_smaller_than_agreed(self):
        order = self.create_order(from_amount=40.0)
        self.fund_deposit(order, 20 * COIN)

        self.worker._check_deposit(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['received_amount'], 20.0)
        self.assertEqual(updated['tx_deposit_id'], 'deposit-tx')

    def test_deposit_landing_after_deadline_still_advances(self):
        # Expiry must never swallow coins that actually arrived.
        order = self.create_order()
        self.service.update_order(order['id'], {'expires_at': self.service.now() - 1000})
        self.fund_deposit(order, 10 * COIN)

        self.worker._check_deposit(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')

    def test_the_deadline_itself_has_not_passed_yet(self):
        order = self.create_order()

        self.at(order['expires_at'])
        self.worker._check_deposit(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

        self.at(order['expires_at'] + 1)
        self.worker._check_deposit(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'expired')

    def test_the_newest_transaction_is_tracked_as_the_deposit(self):
        # Two payments arrived before the first look: both count, the newest
        # one is the transaction whose confirmations are followed
        order = self.create_order()
        self.fund_deposit(order, 4 * COIN, height=100, tx_hash='first-tx')
        self.fund_deposit(order, 6 * COIN, tx_hash='second-tx')

        self.worker._check_deposit(order)

        updated = self.reload(order)
        self.assertEqual(updated['tx_deposit_id'], 'second-tx')
        self.assertEqual(updated['received_amount'], 10.0)
        self.assertEqual(updated['confirm_count'], 0)

    def test_coins_without_a_history_entry_yet_are_waited_for(self):
        # A server can list the coins before their history entry: nothing is
        # recorded until it can name the deposit transaction
        order = self.create_order()
        self.knf_wallet.unspent[order['deposit_scripthash']] = [
            {'tx_hash': 'deposit-tx', 'tx_pos': 0, 'height': 0, 'value': 10 * COIN},
        ]

        self.worker._check_deposit(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_deposit')
        self.assertEqual(updated['received_amount'], 0)
        self.assertIsNone(updated['tx_deposit_id'])

    def test_an_ltc_deposit_is_watched_on_the_ltc_chain(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.knf_wallet.receive(order['deposit_scripthash'], 'wrong-chain-tx', 1 * COIN)
        self.worker._check_deposit(order)
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

        self.fund_deposit(order, 1 * COIN)
        self.worker._check_deposit(order)
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')








############################################################
# TestCheckConfirmations
############################################################
#
# awaiting_confirmations: confirmations counted from block
# heights, a top-up recorded, a vanished deposit sending the
# order back.
############################################################

class TestCheckConfirmations(ExchangeTestCase):

    def advance_to_confirmations(self, amount_sat=10 * COIN, height=0):
        order = self.create_order()
        self.fund_deposit(order, amount_sat, height=height)
        self.worker._check_deposit(order)
        return self.reload(order)

    def test_counts_confirmations_from_heights(self):
        # Deposit mined at height 100, tip at 101 -> 2 confirmations = target.
        order = self.advance_to_confirmations(height=100)
        self.knf_wallet.history[order['deposit_scripthash']][0]['height'] = 100
        self.knf_wallet.tip_height = 101

        self.worker._check_confirmations(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'exchanging')
        self.assertEqual(updated['confirm_count'], 2)

    def test_mempool_tx_has_zero_confirmations(self):
        order = self.advance_to_confirmations(height=0)
        self.worker._check_confirmations(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['confirm_count'], 0)

    def test_topup_during_confirmations_is_recorded(self):
        order = self.advance_to_confirmations(amount_sat=5 * COIN)
        self.fund_deposit(order, 10 * COIN, tx_hash='topup-tx')

        self.worker._check_confirmations(self.reload(order))
        self.assertEqual(self.reload(order)['received_amount'], 15.0)

    def test_vanished_deposit_tx_resets_to_awaiting_deposit(self):
        # Reorg / RBF: the tx we were watching is gone from the history.
        order = self.advance_to_confirmations()
        self.knf_wallet.history[order['deposit_scripthash']] = []

        self.worker._check_confirmations(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_deposit')
        self.assertIsNone(updated['tx_deposit_id'])

    def test_one_confirmation_short_keeps_waiting(self):
        order = self.advance_to_confirmations(height=100)
        self.knf_wallet.tip_height = 100

        self.worker._check_confirmations(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['confirm_count'], 1)

    def test_more_confirmations_than_needed_advance_as_well(self):
        order = self.advance_to_confirmations(height=100)
        self.knf_wallet.tip_height = 150

        self.worker._check_confirmations(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'exchanging')
        self.assertEqual(updated['confirm_count'], 51)

    def test_a_target_of_zero_counts_as_one(self):
        order = self.advance_to_confirmations(height=100)
        self.service.update_order(order['id'], {'confirm_target': 0})
        self.knf_wallet.tip_height = 100

        self.worker._check_confirmations(self.reload(order))

        self.assertEqual(self.reload(order)['status'], 'exchanging')








############################################################
# TestLockExchangeRate
############################################################
#
# exchanging: the payout priced from what actually arrived,
# at the rate in force at the lock, and the coins it pays for
# fixed.
############################################################

class TestLockExchangeRate(ExchangeTestCase):

    def exchanging_order(self, deposit_sat):
        # Confirmed twice at the fake's tip of 100 - deep enough to lock
        order = self.create_order(from_amount=40.0)
        self.fund_deposit(order, deposit_sat, height=99)
        self.service.update_order(order['id'], {'status': 'exchanging'})
        return self.reload(order)

    def test_payout_priced_from_actual_deposit_not_quote(self):
        # The 40-KNF quote must be ignored: only 20 KNF arrived.
        order = self.exchanging_order(20 * COIN)
        self.worker._lock_exchange_rate(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['received_amount'], 20.0)
        self.assertAlmostEqual(updated['to_amount'], 20.0 * RATE_KNF_TO_LTC)
        self.assertEqual(updated['locked_rate'], RATE_KNF_TO_LTC)

    def test_duplicate_utxo_reports_are_not_double_counted(self):
        # The mid-block race: the same outpoint listed from the mempool view
        # AND the confirmed view. Summed naively this doubles the deposit.
        order = self.create_order(from_amount=40.0)
        self.fund_deposit(order, 20 * COIN, height=99, tx_hash='dup-tx')
        self.service.update_order(order['id'], {'status': 'exchanging'})

        # FakeWallet.get_unspent hands back the raw list; the real dedup lives
        # in ExchangeWallet.get_unspent and has its own test - here we only
        # prove the payout follows the coins the wallet reports.
        self.worker._lock_exchange_rate(self.reload(order))
        self.assertAlmostEqual(self.reload(order)['to_amount'], 20.0 * RATE_KNF_TO_LTC)

    def test_vanished_deposit_resets_instead_of_paying_stale_data(self):
        order = self.exchanging_order(20 * COIN)
        self.knf_wallet.unspent[order['deposit_scripthash']] = []

        self.worker._lock_exchange_rate(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

    def test_ltc_to_knf_is_priced_at_the_inverse_rate(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.fund_deposit(order, 2 * COIN, height=99)
        self.service.update_order(order['id'], {'status': 'exchanging'})

        self.worker._lock_exchange_rate(self.reload(order))

        updated = self.reload(order)
        self.assertAlmostEqual(updated['locked_rate'], 1.0 / RATE_KNF_TO_LTC)
        self.assertAlmostEqual(updated['to_amount'], 2.0 / RATE_KNF_TO_LTC)

    def test_the_coins_counted_are_the_ones_the_payout_pays_for(self):
        order = self.exchanging_order(20 * COIN)
        self.fund_deposit(order, 5 * COIN, height=98, tx_hash='second-tx')

        self.worker._lock_exchange_rate(self.reload(order))

        self.assertEqual(json.loads(self.reload(order)['paid_coins']), ['deposit-tx:0', 'second-tx:0'])

    def test_the_rate_in_force_at_the_lock_is_the_one_paid(self):
        # The order keeps the quote it was created with; the payout uses
        # the rate of the moment the deposit confirmed
        order = self.exchanging_order(20 * COIN)

        with patch('app.config.RATE_KNF_TO_LTC', 0.2):
            self.worker._lock_exchange_rate(order)

        updated = self.reload(order)
        self.assertEqual(updated['rate'], RATE_KNF_TO_LTC)
        self.assertEqual(updated['locked_rate'], 0.2)
        self.assertAlmostEqual(updated['to_amount'], 4.0)








############################################################
# TestSendPayout
############################################################
#
# sending: the payout built, persisted, broadcast and
# followed to its confirmation — never built twice, retried
# after a back-off when it cannot get out, and the coins sent
# back when it cannot be made at all.
############################################################

class TestSendPayout(ExchangeTestCase):

    def sending_order(self, to_amount=1.2345678):
        # Locked on 10 KNF that confirmed and still sit on the deposit address
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN, height=99)
        self.service.update_order(order['id'], {'status': 'sending', 'received_amount': 10.0, 'to_amount': to_amount})
        return self.reload(order)

    def test_a_payout_is_broadcast_and_the_order_waits_for_it_to_confirm(self):
        order = self.sending_order()
        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['tx_send_id'], 'payout-txid')
        self.assertEqual(updated['tx_send_raw'], 'payout-raw-hex')
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])
        # Priced correctly and sent to the student's address.
        self.assertEqual(self.ltc_wallet.payout_requests,
                         [('tltc1qstudent', int(round(1.2345678 * COIN)))])

    def test_the_order_completes_once_the_payout_has_confirmed(self):
        order = self.sending_order()
        self.worker._send_payout(order)

        self.ltc_wallet.bury('payout-txid', confirmations=1)
        self.worker._send_payout(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'sending')

        self.ltc_wallet.bury('payout-txid', confirmations=2)
        self.worker._send_payout(self.reload(order))
        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])

    def test_signed_tx_is_persisted_even_if_broadcast_fails(self):
        # The crash-safety core: raw tx hits the DB before the network.
        order = self.sending_order()
        self.ltc_wallet.broadcast_error = ConnectionError('boom')

        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')       # not completed...
        self.assertEqual(updated['tx_send_raw'], 'payout-raw-hex')   # ...but persisted
        self.assertIn('boom', updated['error'])

    def test_pending_payout_is_rebroadcast_not_rebuilt(self):
        # Recovery after the crash above: same tx goes out, no new one built.
        order = self.sending_order()
        self.service.update_order(order['id'], {
            'tx_send_id': 'pending-txid', 'tx_send_raw': 'pending-raw', 'error': None,
        })

        self.worker._send_payout(self.reload(order))

        self.assertEqual(self.reload(order)['status'], 'sending')   # until it confirms
        self.assertEqual(self.ltc_wallet.broadcasts, ['pending-raw'])
        self.assertEqual(self.ltc_wallet.payout_requests, [])   # nothing rebuilt

    def test_pending_payout_already_on_chain_just_completes(self):
        order = self.sending_order()
        self.service.update_order(order['id'], {
            'tx_send_id': 'pending-txid', 'tx_send_raw': 'pending-raw', 'error': None,
        })
        self.ltc_wallet.bury('pending-txid')

        self.worker._send_payout(self.reload(order))

        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.broadcasts, [])     # no rebroadcast needed

    def test_conflicted_pending_payout_is_discarded_for_rebuild(self):
        order = self.sending_order()
        self.service.update_order(order['id'], {
            'tx_send_id': 'pending-txid', 'tx_send_raw': 'pending-raw', 'error': None,
        })
        self.ltc_wallet.broadcast_error = RuntimeError('bad-txns-inputs-missingorspent')

        self.worker._send_payout(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertIsNone(updated['tx_send_id'])
        self.assertIsNone(updated['tx_send_raw'])

    def test_a_payout_below_the_dust_limit_sends_the_coins_back(self):
        # 100 sat of tLTC4 can never be paid; the 10 KNF behind it can go back
        order = self.sending_order(to_amount=0.000001)
        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'refunding')
        self.assertEqual(updated['error'], DUST_100_SAT)
        self.assertEqual(self.ltc_wallet.payout_requests, [])

    def test_coins_too_few_to_send_back_either_fail_the_order(self):
        # A one-input refund costs 1100 sat: 1646 sat would leave dust, 1647
        # sat a refund worth sending
        for received, status in ((0.00001646, 'failed'), (0.00001647, 'refunding')):
            with self.subTest(received=received):
                order = self.sending_order(to_amount=0.000001)
                self.service.update_order(order['id'], {'received_amount': received})

                self.worker._send_payout(self.reload(order))

                updated = self.reload(order)
                self.assertEqual(updated['status'], status)
                self.assertEqual(updated['error'], DUST_100_SAT)

    def test_a_reserve_that_cannot_cover_the_payout_sends_the_coins_back(self):
        order = self.sending_order()
        self.ltc_wallet.payout_error = ReserveShortfall('Insufficient reserve funds: have 0.00104235 tLTC4, need 1.2345819 tLTC4')

        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'refunding')
        self.assertEqual(updated['error'], "The exchange's LTC Testnet reserve could not cover the payout of 1.2345678 LTC Testnet")
        self.assertIsNone(updated['tx_send_raw'])
        self.assertIsNone(updated['paid_coins'])
        self.assertEqual(self.ltc_wallet.broadcasts, [])

    def test_a_payout_that_cannot_get_out_keeps_the_order_sending_with_its_reason(self):
        order = self.sending_order()
        self.ltc_wallet.payout_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['error'], 'Electrum 127.0.0.1:1 unreachable: timed out')
        self.assertIsNone(updated['tx_send_raw'])

    def test_a_failed_attempt_waits_out_the_back_off(self):
        start = self.service.now()
        self.at(start)
        order = self.sending_order()
        self.service.update_order(order['id'], {'error': 'Electrum 127.0.0.1:1 unreachable: timed out'})

        self.at(start + 29_999)
        self.worker._send_payout(self.reload(order))
        self.assertEqual(self.ltc_wallet.payout_requests, [])

        self.at(start + 30_000)
        self.worker._send_payout(self.reload(order))
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])
        self.assertIsNone(self.reload(order)['error'])

    def test_the_amount_is_rounded_to_whole_satoshis(self):
        order = self.sending_order(to_amount=0.123456789)
        self.worker._send_payout(order)
        self.assertEqual(self.ltc_wallet.payout_requests, [('tltc1qstudent', 12345679)])

    def test_the_dust_limit_itself_is_too_small_to_pay(self):
        order = self.sending_order(to_amount=546 / COIN)
        self.worker._send_payout(order)

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'refunding')
        self.assertEqual(updated['error'], "Received amount is too small to pay out (a payout of 0.00000546 LTC Testnet is below the network's minimum of 0.00000547 LTC Testnet)")
        self.assertEqual(self.ltc_wallet.payout_requests, [])

    def test_one_satoshi_above_the_dust_limit_is_paid(self):
        order = self.sending_order(to_amount=547 / COIN)
        self.worker._send_payout(order)

        self.assertEqual(self.reload(order)['tx_send_id'], 'payout-txid')
        self.assertEqual(self.ltc_wallet.payout_requests, [('tltc1qstudent', 547)])

    def test_ltc_to_knf_is_paid_on_the_knf_chain(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.fund_deposit(order, 1 * COIN, height=99)
        self.service.update_order(order['id'], {'status': 'sending', 'received_amount': 1.0, 'to_amount': 8.1})

        self.worker._send_payout(self.reload(order))

        self.assertEqual(self.knf_wallet.payout_requests, [('knf1qstudent', 810000000)])
        self.assertEqual(self.ltc_wallet.payout_requests, [])

    def test_a_rebroadcast_the_network_already_knows_is_waited_for_not_rebuilt(self):
        for answer in ('transaction already in block chain', 'txn-already-known', 'Duplicate transaction'):
            with self.subTest(answer=answer):
                order = self.sending_order()
                self.service.update_order(order['id'], {
                    'tx_send_id': 'pending-txid', 'tx_send_raw': 'pending-raw', 'error': None,
                })
                self.ltc_wallet.broadcast_error = RuntimeError(f'Electrum error: {answer}')

                self.worker._send_payout(self.reload(order))

                updated = self.reload(order)
                self.assertEqual(updated['status'], 'sending')
                self.assertEqual(updated['tx_send_raw'], 'pending-raw')
                self.assertEqual(self.ltc_wallet.payout_requests, [])

    def test_an_unexplained_rebroadcast_failure_is_recorded_and_retried(self):
        # Neither "already known" nor a conflict: the signed payout is kept and
        # tried again after the back-off
        order = self.sending_order()
        self.service.update_order(order['id'], {
            'tx_send_id': 'pending-txid', 'tx_send_raw': 'pending-raw', 'error': None,
        })
        self.ltc_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        self.worker._send_payout(self.reload(order))

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'sending')
        self.assertEqual(updated['tx_send_raw'], 'pending-raw')
        self.assertEqual(updated['error'], 'Electrum 127.0.0.1:1 unreachable: timed out')








############################################################
# TestSweep
############################################################
#
# Completed deposits swept into the reserve — the coins their
# payout paid for, nothing else — and what each outcome is
# recorded as.
############################################################

class TestSweep(ExchangeTestCase):

    def completed_order(self):
        order = self.create_order()
        self.service.update_order(order['id'], {'status': 'completed', 'received_amount': 10.0})
        return self.reload(order)

    def test_completed_order_is_swept_to_reserve(self):
        order = self.completed_order()
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(9.999 * COIN))

        self.worker._sweep_finished_orders()

        updated = self.reload(order)
        self.assertEqual(updated['sweep_state'], 'swept')
        self.assertEqual(updated['tx_sweep_id'], 'sweep-txid')
        self.assertEqual(self.knf_wallet.broadcasts, ['sweep-raw'])

    def test_swept_order_is_not_swept_twice(self):
        order = self.completed_order()
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(9.999 * COIN))

        self.worker._sweep_finished_orders()
        self.worker._sweep_finished_orders()

        self.assertEqual(self.knf_wallet.broadcasts, ['sweep-raw'])   # exactly once

    def test_empty_address_marks_swept_without_broadcast(self):
        # Covers the crash-after-broadcast case: UTXOs gone, nothing to do.
        order = self.completed_order()
        self.knf_wallet.sweep_result = None

        self.worker._sweep_finished_orders()

        self.assertEqual(self.reload(order)['sweep_state'], 'swept')
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_an_address_emptied_while_its_deposit_is_still_on_chain_reads_as_swept(self):
        # The history still lists the deposit, only its coins are spent - by
        # a sweep broadcast just before a crash
        order = self.completed_order()
        self.fund_deposit(order, 10 * COIN, height=99)
        self.service.update_order(order['id'], {'tx_deposit_id': 'deposit-tx'})
        self.knf_wallet.unspent[order['deposit_scripthash']] = []

        self.worker._sweep_finished_orders()

        self.assertEqual(self.reload(order)['sweep_state'], 'swept')

    def test_a_deposit_gone_from_the_chain_is_marked_missing_and_reported(self):
        order = self.completed_order()
        self.service.update_order(order['id'], {'tx_deposit_id': 'deposit-tx'})

        with self.assertLogs('exchange.worker', 'ERROR') as logs:
            self.worker._sweep_finished_orders()

        updated = self.reload(order)
        self.assertEqual(updated['sweep_state'], 'missing')
        self.assertIsNone(updated['tx_sweep_id'])
        self.assertIn(f"Deposit deposit-tx of order {order['id']} is gone from the chain after its payout",
                      '\n'.join(logs.output))

    def test_dust_leftover_marks_dust(self):
        order = self.completed_order()
        self.knf_wallet.sweep_result = None
        self.fund_deposit(order, 100)    # 100 sat still sitting there

        self.worker._sweep_finished_orders()
        self.assertEqual(self.reload(order)['sweep_state'], 'dust')

    def test_expired_orders_are_never_swept(self):
        order = self.create_order()
        self.service.update_order(order['id'], {'status': 'expired'})

        self.worker._sweep_finished_orders()
        self.assertIsNone(self.reload(order)['sweep_state'])

    def test_an_order_that_did_not_go_through_is_never_swept(self):
        # Its coins are the student's: sent back, or too few for that
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', 1500)
        for status in ('failed', 'refunding', 'refunded'):
            with self.subTest(status=status):
                order = self.create_order()
                self.service.update_order(order['id'], {'status': status, 'received_amount': 0.00001})

                self.worker._sweep_finished_orders()

                self.assertIsNone(self.reload(order)['sweep_state'])
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_only_the_coins_the_payout_paid_for_are_swept(self):
        # A payment that arrived after the rate lock stays, to be sent back
        order = self.completed_order()
        self.fund_deposit(order, 10 * COIN, height=99, tx_hash='deposit-tx')
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')
        self.service.update_order(order['id'], {'paid_coins': '["deposit-tx:0"]'})
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(9.999 * COIN))

        self.worker._sweep_finished_orders()

        self.assertEqual(self.knf_wallet.sweep_requests,
                         [[{'tx_hash': 'deposit-tx', 'tx_pos': 0, 'height': 99, 'value': 10 * COIN}]])
        self.assertEqual(self.reload(order)['sweep_state'], 'swept')

    def test_paid_for_coins_too_few_to_sweep_mark_dust_whatever_else_is_there(self):
        order = self.completed_order()
        self.fund_deposit(order, 100, height=99, tx_hash='deposit-tx')
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')
        self.service.update_order(order['id'], {'paid_coins': '["deposit-tx:0"]'})

        self.worker._sweep_finished_orders()

        self.assertEqual(self.reload(order)['sweep_state'], 'dust')

    def test_an_order_locked_before_its_coins_were_tracked_sweeps_everything(self):
        order = self.completed_order()
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(9.999 * COIN))

        self.worker._sweep_finished_orders()

        self.assertEqual(self.knf_wallet.sweep_requests, [None])

    def test_an_order_that_received_nothing_is_never_swept(self):
        order = self.create_order()
        self.service.update_order(order['id'], {'status': 'completed'})
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', 1500)

        self.worker._sweep_finished_orders()

        self.assertIsNone(self.reload(order)['sweep_state'])
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_a_sweep_that_fails_is_tried_again_on_a_later_pass(self):
        order = self.completed_order()
        self.knf_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(9.999 * COIN))
        self.knf_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        with self.assertLogs('exchange.worker', 'ERROR'):
            self.worker._sweep_finished_orders()
        self.assertIsNone(self.reload(order)['sweep_state'])

        self.knf_wallet.broadcast_error = None
        self.worker._sweep_finished_orders()
        self.assertEqual(self.reload(order)['sweep_state'], 'swept')

    def test_the_sweep_runs_on_the_chain_the_deposit_came_from(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.service.update_order(order['id'], {'status': 'completed', 'received_amount': 1.0})
        self.ltc_wallet.sweep_result = ('sweep-txid', 'sweep-raw', int(0.999 * COIN))

        self.worker._sweep_finished_orders()

        self.assertEqual(self.ltc_wallet.broadcasts, ['sweep-raw'])
        self.assertEqual(self.knf_wallet.broadcasts, [])








############################################################
# TestLateDeposits
############################################################
#
# Expired orders watched for late coins — for a day, once a
# minute.
############################################################

class TestLateDeposits(ExchangeTestCase):

    def expired_order(self):
        order = self.create_order()
        self.at(order['expires_at'] + 1)
        self.worker._check_deposit(order)
        self.assertEqual(self.reload(order)['status'], 'expired')
        return self.reload(order)

    def test_coins_arriving_after_the_expiry_take_the_order_back_into_the_lifecycle(self):
        order = self.expired_order()
        self.fund_deposit(order, 10 * COIN)

        self.tick()

        updated = self.reload(order)
        self.assertEqual(updated['status'], 'awaiting_confirmations')
        self.assertEqual(updated['received_amount'], 10.0)
        self.assertEqual(updated['tx_deposit_id'], 'deposit-tx')

    def test_an_expired_order_with_nothing_on_its_address_stays_expired(self):
        order = self.expired_order()
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'expired')

    def test_after_a_day_an_expired_order_is_no_longer_watched(self):
        order = self.expired_order()
        self.at(order['expires_at'] + 24 * 60 * 60 * 1000 + 1)
        self.fund_deposit(order, 10 * COIN)

        self.tick()

        self.assertEqual(self.reload(order)['status'], 'expired')

    def test_expired_orders_are_looked_at_once_a_minute_not_every_pass(self):
        order = self.expired_order()
        start = order['expires_at'] + 1
        self.tick()
        self.fund_deposit(order, 10 * COIN)

        self.at(start + 30 * 1000)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'expired')

        self.at(start + 60 * 1000)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')








############################################################
# TestWorkerThread
############################################################
#
# The daemon thread: started once, stopped after its pass,
# started again.
############################################################

class TestWorkerThread(ExchangeTestCase):

    def test_start_runs_the_loop_on_one_daemon_thread(self):
        passes, release = [], threading.Event()

        def loop():
            passes.append(threading.current_thread())
            release.wait(5)

        with patch.object(self.worker, '_loop', side_effect=loop):
            self.worker.start()
            self.worker.start()     # already running: no second thread
            release.set()
            self.worker.thread.join(5)

        self.assertEqual(len(passes), 1)
        self.assertTrue(passes[0].daemon)

    def test_stop_ends_the_loop_after_its_current_pass(self):
        with patch('app.worker.WORKER_INTERVAL_S', 0.01):
            self.worker.start()
            self.worker.stop()

        self.assertFalse(self.worker.thread.is_alive())

    def test_a_stopped_worker_can_be_started_again(self):
        with patch('app.worker.WORKER_INTERVAL_S', 0.01):
            self.worker.start()
            self.worker.stop()
            first = self.worker.thread

            self.worker.start()
            self.assertTrue(self.worker.thread.is_alive())
            self.assertIsNot(self.worker.thread, first)
            self.worker.stop()
