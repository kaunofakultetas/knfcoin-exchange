############################################################
#  [*] Several deposits — when the student pays more than once
#
#  Nothing stops a student from paying an order's address
#  again: an amount sent in instalments, a small test payment
#  before the real one, more than was agreed, or another
#  swap's worth after this one was paid out. These tests send
#  an order several payments of different sizes at every stage
#  of its life and count what the student is paid and sent
#  back (on CoinWallets, so payouts, sweeps and refunds move
#  the coins they spend):
#
#    - everything that arrives before the rate is locked is
#      added up and paid for, however many payments and of
#      whatever size: sent before the first look or while the
#      first ones confirm (the lock waits for the youngest),
#      less or more than agreed, payments too small to pay out
#      on their own, a small test payment and then the rest,
#      and an expired order paid late in instalments
#    - coins that arrive after the lock are not exchanged but
#      sent back where they came from: while the payout
#      confirms (the sweep takes only what the payout paid
#      for), after the order is done, after a test payment too
#      small to pay out failed the order — the two then going
#      back together, the order refunded after all — and while
#      the order's coins are already on their way back
############################################################


from app.wallet import COIN
from app.config import RATE_KNF_TO_LTC
from app.service import AMOUNT_LIMITS, KNF

from tests.base import ExchangeTestCase
from tests.fakes import CoinWallet


# Where every order here is paid out
STUDENT = 'tltc1qstudent'

# What a one-input refund (or sweep) costs the coins it sends, and what a
# two-input one costs, at the 10 sat/vbyte the tests run with
REFUND_FEE = 1100
TWO_COIN_REFUND_FEE = (2 * 68 + 31 + 11) * 10


# What a KNF deposit is paid, in tLTC4 satoshis, priced the way the rate
# lock prices it
def paid_for(knf):
    return int(round(knf * RATE_KNF_TO_LTC * COIN))








############################################################
# SeveralDepositsTestCase
############################################################
#
# CoinWallets on both chains, 100 tLTC4 in the reserve the
# KNF -> tLTC4 orders here are paid from, the service clock
# under the test's hand — and the helpers a timeline of
# payments needs: a payment sent, payments confirmed, the
# worker left to run while every transaction the exchange
# sends confirms, and what the student has been paid.
#
# Used by:
#   - every test class below
############################################################

class SeveralDepositsTestCase(ExchangeTestCase):

    wallet_class = CoinWallet

    def setUp(self):
        super().setUp()
        self.ltc_wallet.fund_reserve('top-up-1', 100 * COIN)
        self.clock = self.service.now()
        self.at(self.clock)

    def pay(self, order, tx_hash, knf):
        # One payment to the order's deposit address, waiting in the mempool
        self.knf_wallet.receive(order['deposit_scripthash'], tx_hash, int(round(knf * COIN)))

    def confirm(self, *tx_hashes):
        # Mined in the next block, with one more on top: two confirmations,
        # the KNF target
        height = self.knf_wallet.tip_height + 1
        for tx_hash in tx_hashes:
            self.knf_wallet.mine(tx_hash, height)
        self.knf_wallet.tip_height = height + 1

    def settle(self, minutes=5):
        # The worker left to run, a pass every 5 seconds, while every payout
        # and sweep the exchange sends confirms on its chain
        for _ in range(minutes * 12):
            self.clock += 5 * 1000
            self.at(self.clock)
            self.tick()
            for wallet in (self.knf_wallet, self.ltc_wallet):
                for txid in wallet.known_txs - set(wallet.tx_heights):
                    wallet.bury(txid)

    def paid(self):
        # Everything the student has been paid so far, in tLTC4 satoshis
        return sum(amount for address, amount in self.ltc_wallet.payouts if address == STUDENT)

    def reserve_sat(self, wallet):
        return wallet.get_received_sat(wallet.reserve.scripthash)








############################################################
# TestPaymentsBeforeTheLock
############################################################
#
# Payments that arrive before the rate is locked: all of them
# added up and paid for in one payout.
############################################################

class TestPaymentsBeforeTheLock(SeveralDepositsTestCase):

    def test_payments_sent_before_the_first_look_are_added_up(self):
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 2.5)
        self.pay(order, 'payment-2', 4.0)
        self.pay(order, 'payment-3', 3.5)

        self.tick()
        self.assertEqual(self.reload(order)['received_amount'], 10.0)

        self.confirm('payment-1', 'payment-2', 'payment-3')
        self.settle()

        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(10.0))])

    def test_a_payment_sent_while_the_first_confirms_is_paid_with_it(self):
        # The count starts over from the youngest payment, the amount shown
        # growing with it
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 6.0)
        self.knf_wallet.mine('payment-1', 101)
        self.knf_wallet.tip_height = 101
        self.tick()
        self.tick()
        self.assertEqual(self.reload(order)['confirm_count'], 1)

        self.pay(order, 'payment-2', 4.0)
        self.tick()
        counting = self.reload(order)
        self.assertEqual((counting['status'], counting['received_amount'], counting['confirm_count']),
                         ('awaiting_confirmations', 10.0, 0))

        self.confirm('payment-2')
        self.settle()
        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(10.0))])

    def test_less_than_agreed_in_instalments_is_paid_for_what_arrived(self):
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 3.0)
        self.pay(order, 'payment-2', 2.0)
        self.confirm('payment-1', 'payment-2')

        self.settle()

        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(5.0))])

    def test_more_than_agreed_is_paid_for_in_full(self):
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 8.0)
        self.pay(order, 'payment-2', 7.0)
        self.confirm('payment-1', 'payment-2')

        self.settle()

        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(15.0))])

    def test_payments_too_small_to_pay_out_alone_are_paid_for_together(self):
        # 2000 sat of KNF is worth 247 sat of tLTC4, below the dust limit;
        # three of them are worth paying out
        order = self.create_order(from_amount=AMOUNT_LIMITS[KNF]['min'])
        for number in (1, 2, 3):
            self.pay(order, f'payment-{number}', 0.00002)
        self.confirm('payment-1', 'payment-2', 'payment-3')

        self.settle()

        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(0.00006))])

    def test_a_small_test_payment_and_then_the_rest_are_paid_for_together(self):
        # The rest arrives before the test payment is deep enough to lock
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'test-payment', 0.00001)
        self.tick()

        self.pay(order, 'payment', 10.0)
        self.confirm('test-payment', 'payment')
        self.settle()

        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(10.00001))])

    def test_an_expired_order_paid_late_in_instalments_is_paid_for_all_of_it(self):
        order = self.create_order(from_amount=10.0)
        self.clock = order['expires_at'] + 1
        self.at(self.clock)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'expired')

        self.pay(order, 'payment-1', 4.0)
        self.pay(order, 'payment-2', 6.0)
        self.confirm('payment-1', 'payment-2')
        self.settle()

        self.assertEqual(self.reload(order)['status'], 'completed')
        self.assertEqual(self.ltc_wallet.payouts, [(STUDENT, paid_for(10.0))])








############################################################
# TestPaymentsAfterTheLock
############################################################
#
# Payments that arrive once the rate is locked: the payout
# pays for the coins the lock counted and nothing else, and
# the later ones go back to the addresses they came from.
############################################################

class TestPaymentsAfterTheLock(SeveralDepositsTestCase):

    def test_a_payment_sent_while_the_payout_confirms_is_sent_back(self):
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 10.0)
        self.confirm('payment-1')
        for _ in range(4):
            self.tick()
        self.assertEqual(self.reload(order)['tx_send_id'], 'payout-1')

        self.pay(order, 'payment-2', 5.0)
        self.confirm('payment-2')
        self.settle()

        self.assertEqual(self.paid(), paid_for(10.0))
        self.assertEqual(self.knf_wallet.refunds, [('knf1qfrom-payment-2', 5 * COIN - REFUND_FEE)])
        # The sweep took only the coins the payout paid for
        self.assertEqual(self.reserve_sat(self.knf_wallet), 10 * COIN - REFUND_FEE)
        done = self.reload(order)
        self.assertEqual((done['status'], done['received_amount']), ('completed', 10.0))
        self.assertEqual([refund['confirmed'] for refund in done['refunds']], [True])

    def test_a_payment_sent_after_the_swap_is_done_is_sent_back(self):
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 10.0)
        self.confirm('payment-1')
        self.settle()
        self.assertEqual(self.reload(order)['sweep_state'], 'swept')

        self.pay(order, 'payment-2', 5.0)
        self.confirm('payment-2')
        self.settle()

        self.assertEqual(self.paid(), paid_for(10.0))
        self.assertEqual(self.knf_wallet.refunds, [('knf1qfrom-payment-2', 5 * COIN - REFUND_FEE)])

    def test_the_payment_after_a_test_payment_too_small_to_pay_out_goes_back_with_it(self):
        # 1000 sat of KNF is worth 123 sat of tLTC4, below the dust limit, and
        # too little to send back on its own; both payments came from the
        # student's wallet
        self.knf_wallet.senders = {'test-payment': 'knf1qstudent', 'payment': 'knf1qstudent'}
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'test-payment', 0.00001)
        self.confirm('test-payment')
        for _ in range(4):
            self.tick()
        self.assertEqual(self.reload(order)['status'], 'failed')

        self.pay(order, 'payment', 10.0)
        self.confirm('payment')
        self.settle()

        # Its coins went back after all: no longer failed
        self.assertEqual(self.paid(), 0)
        self.assertEqual(self.knf_wallet.refunds, [('knf1qstudent', 10 * COIN + 1000 - TWO_COIN_REFUND_FEE)])
        self.assertEqual(self.reload(order)['status'], 'refunded')

    def test_a_payment_sent_while_the_coins_go_back_goes_back_too(self):
        # 1000 KNF sent for a 10 KNF order are worth 123.5 tLTC4 — more than
        # the reserve's 100 can pay
        self.knf_wallet.senders = {'payment-1': 'knf1qstudent', 'payment-2': 'knf1qstudent'}
        order = self.create_order(from_amount=10.0)
        self.pay(order, 'payment-1', 1000.0)
        self.confirm('payment-1')
        for _ in range(5):
            self.tick()
        self.assertEqual(self.knf_wallet.refunds, [('knf1qstudent', 1000 * COIN - REFUND_FEE)])

        self.pay(order, 'payment-2', 500.0)
        self.confirm('payment-2')
        self.settle()

        self.assertEqual(self.paid(), 0)
        self.assertEqual(self.knf_wallet.refunds, [
            ('knf1qstudent', 1000 * COIN - REFUND_FEE),
            ('knf1qstudent', 500 * COIN - REFUND_FEE),
        ])
        self.assertEqual(self.reload(order)['status'], 'refunded')
