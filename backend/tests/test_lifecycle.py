############################################################
#  [*] Lifecycle tests — whole orders through the worker loop
#
#  Orders driven by tick(), one pass of the real worker loop
#  at a time, the way its daemon thread drives them:
#
#    - KNF Coin to LTC Testnet and back again, from creation
#      through the deposit, its confirmations, the rate lock
#      and the payout — completed once the payout confirms on
#      the receiving chain — to the sweep of the deposit into
#      the reserve, each on its own chains
#    - the side exits: an order nobody pays expires once its
#      deadline has passed, one whose payout the reserve
#      cannot cover sends the coins back to their sender and
#      is refunded once the refund confirms, and a deposit too
#      small to pay out or to send back fails, its coins left
#      where they are
#    - a pass moves every active order one step, and an order
#      that raises costs only itself
#    - recovery: a payout that cannot get out (Electrum out of
#      reach) waits out its back-off and goes through once it
#      can; a payout interrupted between signing and
#      broadcasting is finished, never paid twice; the loop
#      outlives a database error
#    - late coins: an expired order paid after its deadline is
#      taken back up and paid like any other
############################################################


import sqlite3
from unittest.mock import Mock, patch

from app.wallet import COIN, ReserveShortfall
from app.config import RATE_KNF_TO_LTC
from app.service import AMOUNT_LIMITS, KNF, LTC

from tests.base import ExchangeTestCase


# What the deposit wallet's sweep answers: its txid, its raw hex and the
# 10 coins less a one-input sweep's fee
SWEEP = ('sweep-txid', 'sweep-raw', 10 * COIN - 1100)








############################################################
# TestHappyPaths
############################################################
#
# Whole swaps in both directions, from creation to the sweep
# of the deposit, and a finished order left alone after.
############################################################

class TestHappyPaths(ExchangeTestCase):

    def test_knf_to_ltc_from_creation_to_the_sweep(self):
        order = self.create_order(from_amount=10.0)
        knf, ltc = self.knf_wallet, self.ltc_wallet

        self.tick()
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

        knf.receive(order['deposit_scripthash'], 'deposit-tx', 10 * COIN)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')

        knf.mine('deposit-tx', 101)
        knf.tip_height = 101
        self.tick()
        self.assertEqual(self.reload(order)['confirm_count'], 1)
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')

        knf.tip_height = 102
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'exchanging')

        self.tick()
        locked = self.reload(order)
        self.assertEqual(locked['status'], 'sending')
        self.assertEqual(locked['locked_rate'], RATE_KNF_TO_LTC)

        self.tick()
        sent = self.reload(order)
        self.assertEqual(sent['status'], 'sending')
        self.assertEqual(sent['tx_send_id'], 'payout-txid')

        # The payout confirms on the tLTC4 chain; the deposit is swept on KNF
        ltc.bury('payout-txid')
        knf.sweep_result = SWEEP
        self.tick()
        done = self.reload(order)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(done['tx_send_id'], 'payout-txid')
        self.assertEqual(done['sweep_state'], 'swept')
        self.assertEqual(done['tx_sweep_id'], 'sweep-txid')
        self.assertEqual(ltc.payout_requests, [('tltc1qstudent', int(round(10 * RATE_KNF_TO_LTC * COIN)))])
        self.assertEqual(ltc.broadcasts, ['payout-raw-hex'])
        self.assertEqual(knf.broadcasts, ['sweep-raw'])

    def test_a_finished_order_is_left_alone_by_later_passes(self):
        order = self.create_order()
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-tx', 10 * COIN, height=101)
        self.knf_wallet.tip_height = 102
        self.knf_wallet.sweep_result = SWEEP
        for _ in range(4):
            self.tick()
        self.ltc_wallet.bury('payout-txid')
        self.tick()
        self.assertEqual(self.reload(order)['sweep_state'], 'swept')

        for _ in range(3):
            self.tick()

        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])
        self.assertEqual(self.knf_wallet.broadcasts, ['sweep-raw'])

    def test_ltc_to_knf_runs_on_the_other_chains(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        knf, ltc = self.knf_wallet, self.ltc_wallet
        ltc.receive(order['deposit_scripthash'], 'deposit-tx', 1 * COIN, height=101)
        ltc.tip_height = 102
        ltc.sweep_result = SWEEP

        for status in ('awaiting_confirmations', 'exchanging', 'sending', 'sending'):
            self.tick()
            self.assertEqual(self.reload(order)['status'], status)

        knf.bury('payout-txid')
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'completed')

        self.assertEqual(knf.payout_requests, [('knf1qstudent', int(round(1.0 / RATE_KNF_TO_LTC * COIN)))])
        self.assertEqual(knf.broadcasts, ['payout-raw-hex'])
        self.assertEqual(ltc.broadcasts, ['sweep-raw'])
        self.assertEqual(ltc.payout_requests, [])








############################################################
# TestSideExits
############################################################
#
# The orders that end early: unpaid past the deadline, not
# payable by the reserve — refunded — and paid too little to
# pay out or send back.
############################################################

class TestSideExits(ExchangeTestCase):

    def test_an_order_nobody_pays_expires_once_its_deadline_has_passed(self):
        order = self.create_order()

        self.at(order['expires_at'])
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')

        self.at(order['expires_at'] + 1)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'expired')

        self.tick()
        self.assertIsNone(self.reload(order)['sweep_state'])

    def test_an_order_the_reserve_cannot_pay_out_is_refunded(self):
        order = self.create_order()
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-tx', 10 * COIN, height=101)
        self.knf_wallet.tip_height = 102
        self.ltc_wallet.payout_error = ReserveShortfall('Insufficient reserve funds: have 0.00104235 tLTC4, need 1.2345819 tLTC4')

        for status in ('awaiting_confirmations', 'exchanging', 'sending', 'refunding', 'refunding'):
            self.tick()
            self.assertEqual(self.reload(order)['status'], status)

        # The refund is out, to the address the deposit came from
        refunding = self.reload(order)
        self.assertEqual(refunding['refunds'], [{
            'txid': 'refund-1', 'confirmed': False, 'created_at': refunding['refunds'][0]['created_at'],
            'recipients': [{'address': 'knf1qfrom-deposit-tx', 'amount': (10 * COIN - 1100) / COIN}],
        }])
        self.assertEqual(self.knf_wallet.broadcasts, ['refund-1-raw'])

        self.knf_wallet.bury('refund-1')
        self.tick()
        refunded = self.reload(order)
        self.assertEqual(refunded['status'], 'refunded')
        self.assertTrue(refunded['refunds'][0]['confirmed'])
        self.assertIsNone(refunded['sweep_state'])
        self.assertEqual(self.ltc_wallet.broadcasts, [])

    def test_a_deposit_too_small_to_pay_out_or_send_back_fails(self):
        # 1000 sat of KNF is worth 123 sat of tLTC4 — below the dust limit —
        # and a refund's fee would eat all of it
        order = self.create_order(from_amount=AMOUNT_LIMITS[KNF]['min'])
        self.knf_wallet.receive(order['deposit_scripthash'], 'dust-tx', 1000, height=101)
        self.knf_wallet.tip_height = 102

        for _ in range(4):
            self.tick()

        failed = self.reload(order)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error'], "Received amount is too small to pay out (a payout of 0.00000123 LTC Testnet is below the network's minimum of 0.00000547 LTC Testnet)")
        self.assertIsNone(failed['sweep_state'])
        self.assertEqual(failed['refunds'], [])
        self.assertEqual(self.ltc_wallet.payout_requests, [])
        self.assertEqual(self.knf_wallet.broadcasts, [])








############################################################
# TestThePass
############################################################
#
# One pass of the loop: every active order moves one step,
# an order that raises costs only itself, and the loop
# outlives a database error.
############################################################

class TestThePass(ExchangeTestCase):

    def test_one_pass_moves_every_active_order_one_step(self):
        waiting = self.create_order()
        self.fund_deposit(waiting, 10 * COIN)
        exchanging = self.create_order()
        self.fund_deposit(exchanging, 10 * COIN, height=99)
        self.service.update_order(exchanging['id'], {'status': 'exchanging'})

        self.tick()

        self.assertEqual(self.reload(waiting)['status'], 'awaiting_confirmations')
        self.assertEqual(self.reload(exchanging)['status'], 'sending')
        self.assertEqual(self.ltc_wallet.payout_requests, [])

    def test_an_order_that_raises_costs_only_itself(self):
        broken = self.create_order()
        self.fund_deposit(broken, 10 * COIN)
        healthy = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.fund_deposit(healthy, 1 * COIN)
        self.knf_wallet.get_received_sat = Mock(side_effect=RuntimeError('Electrum error: server busy'))

        with self.assertLogs('exchange.worker', 'ERROR') as logs:
            self.tick()

        self.assertEqual(self.reload(broken)['status'], 'awaiting_deposit')
        self.assertEqual(self.reload(healthy)['status'], 'awaiting_confirmations')
        self.assertIn(f"Error on order {broken['id']}: Electrum error: server busy", '\n'.join(logs.output))

    def test_the_loop_outlives_a_database_error(self):
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN)

        with patch('app.worker.get_db_connection', side_effect=sqlite3.OperationalError('database is locked')):
            with self.assertLogs('exchange.worker', 'ERROR') as logs:
                self.tick()
        self.assertIn('Loop error: database is locked', '\n'.join(logs.output))

        self.tick()
        self.assertEqual(self.reload(order)['status'], 'awaiting_confirmations')








############################################################
# TestPayoutRecovery
############################################################
#
# Payouts that do not go through at the first attempt: an
# Electrum server out of reach, and a crash between signing
# and broadcasting.
############################################################

class TestPayoutRecovery(ExchangeTestCase):

    def sending_order(self):
        # Locked on 10 KNF that confirmed and still sit on the deposit address
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN, height=99)
        self.service.update_order(order['id'], {
            'status': 'sending', 'received_amount': 10.0,
            'locked_rate': RATE_KNF_TO_LTC, 'to_amount': 10.0 * RATE_KNF_TO_LTC,
        })
        return self.reload(order)

    def test_a_payout_that_cannot_get_out_waits_out_its_back_off_and_goes_through(self):
        start = self.service.now()
        self.at(start)
        order = self.sending_order()
        self.ltc_wallet.payout_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        self.tick()
        self.assertEqual(self.reload(order)['error'], 'Electrum 127.0.0.1:1 unreachable: timed out')

        # Back — but the next attempt waits out the 30-second back-off
        self.ltc_wallet.payout_error = None
        self.at(start + 10 * 1000)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'sending')
        self.assertEqual(len(self.ltc_wallet.payout_requests), 1)

        self.at(start + 31 * 1000)
        self.tick()
        sent = self.reload(order)
        self.assertEqual(sent['tx_send_id'], 'payout-txid')
        self.assertIsNone(sent['error'])
        self.assertEqual(len(self.ltc_wallet.payout_requests), 2)

        self.ltc_wallet.bury('payout-txid')
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'completed')

    def test_a_payout_interrupted_before_its_broadcast_is_finished_not_paid_twice(self):
        start = self.service.now()
        self.at(start)
        order = self.sending_order()
        self.ltc_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        self.tick()
        interrupted = self.reload(order)
        self.assertEqual(interrupted['status'], 'sending')
        self.assertEqual(interrupted['tx_send_raw'], 'payout-raw-hex')

        self.ltc_wallet.broadcast_error = None
        self.at(start + 31 * 1000)
        self.tick()
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])

        self.ltc_wallet.bury('payout-txid')
        self.tick()

        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.broadcasts, ['payout-raw-hex'])
        self.assertEqual(len(self.ltc_wallet.payout_requests), 1)








############################################################
# TestLateCoins
############################################################
#
# An expired order paid after its deadline, taken up and
# paid like any other.
############################################################

class TestLateCoins(ExchangeTestCase):

    def test_an_order_paid_after_its_deadline_is_taken_up_and_paid(self):
        order = self.create_order()
        self.at(order['expires_at'] + 1)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'expired')

        # The student pays a few minutes late; the coins confirm
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-tx', 10 * COIN, height=101)
        self.knf_wallet.tip_height = 102
        self.at(order['expires_at'] + 5 * 60 * 1000)

        for status in ('awaiting_confirmations', 'exchanging', 'sending', 'sending'):
            self.tick()
            self.assertEqual(self.reload(order)['status'], status)

        self.ltc_wallet.bury('payout-txid')
        self.tick()
        done = self.reload(order)
        self.assertEqual(done['status'], 'completed')
        self.assertEqual(self.ltc_wallet.payout_requests, [('tltc1qstudent', int(round(10 * RATE_KNF_TO_LTC * COIN)))])
