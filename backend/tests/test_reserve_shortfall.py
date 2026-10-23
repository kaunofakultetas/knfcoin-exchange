############################################################
#  [*] Reserve shortfall tests — when the exchange cannot pay
#
#  A payout comes out of the reserve of the chain the student
#  receives on, and only the operator's top-ups and the
#  deposits swept in from the other direction refill it — so
#  a reserve can hold less than an order would be owed. These
#  tests run orders against reserves that hold coins of their
#  own (CoinWallets) and follow what the exchange does then:
#
#    - an order its reserve cannot cover is refused before the
#      student pays anything, with the most it can take — the
#      payouts owed to the orders paid into counted once, never
#      twice — and the swap form and the reserves page are told
#      what can still be paid out
#    - an order that could be covered when it was taken but no
#      longer can when its payout is due (another order paid
#      first, or more sent than agreed) is not paid: its coins
#      go back to the addresses they came from, and it is
#      refunded once the refund confirms — nothing paid out,
#      nothing swept, the reserve untouched
#    - orders share their reserve: the change of one payout
#      pays the next, and what a sweep brings in from the other
#      direction lets the exchange take an order it refused
#    - two payouts that pick the same reserve coin, the
#      server's view not showing the first one yet, still pay
#      each student exactly once — the second a minute late
#
#  (How the wallet picks reserve coins, words a shortfall and
#  plans a refund is tested on the real wallet in
#  test_wallet.py; the refund step itself in test_refunds.py.)
############################################################


from app.wallet import COIN
from app.config import RATE_KNF_TO_LTC
from app.service import KNF, LTC, ValidationError

from tests.base import ExchangeTestCase
from tests.fakes import CoinWallet


# What a one-input payout costs the reserve on top of its amount, at the
# 10 sat/vbyte the tests run with
PAYOUT_FEE = 1410

# What a one-input refund (or sweep) costs the coins it sends
REFUND_FEE = 1100


# What a KNF deposit is paid, in tLTC4 satoshis, priced the way the rate
# lock prices it
def paid_for(knf):
    return int(round(knf * RATE_KNF_TO_LTC * COIN))








############################################################
# ShortfallTestCase
############################################################
#
# CoinWallets on both chains, their reserves empty until a
# test funds them, the service clock frozen at the start, and
# KNF -> tLTC4 orders brought to the moment their payout is
# due: paid in full, each by a deposit of its own that has
# confirmed, their rates locked.
#
# Used by:
#   - every test class below
############################################################

class ShortfallTestCase(ExchangeTestCase):

    wallet_class = CoinWallet

    def setUp(self):
        super().setUp()
        self.start = self.service.now()
        self.at(self.start)

    def locked(self, *amounts):
        # One order per amount (one of 10 KNF when none is given), the n-th
        # paying tltc1qstudent<n> and paid into by deposit-<n>; all of them
        # are taken before any is paid into, and the next pass pays them,
        # oldest first
        orders = [self.create_order(from_amount=amount, destination=f'tltc1qstudent{number}')
                  for number, amount in enumerate(amounts or (10.0,), start=1)]
        for number, order in enumerate(orders, start=1):
            self.knf_wallet.receive(order['deposit_scripthash'], f'deposit-{number}',
                                    int(round(order['from_amount'] * COIN)), height=99)

        for _ in range(3):
            self.tick()

        orders = [self.reload(order) for order in orders]
        for order in orders:
            self.assertEqual(order['status'], 'sending')
        return orders

    def reserve_sat(self, wallet):
        return wallet.get_received_sat(wallet.reserve.scripthash)








############################################################
# TestTakingAnOrder
############################################################
#
# Before the student pays: an order is taken only while its
# reserve can cover it, and the pages are told how much can
# still be paid out.
############################################################

class TestTakingAnOrder(ShortfallTestCase):

    def test_an_order_the_reserve_can_cover_is_taken(self):
        self.ltc_wallet.fund_reserve('top-up-1', paid_for(10.0) + PAYOUT_FEE)
        self.assertEqual(self.create_order(from_amount=10.0)['status'], 'awaiting_deposit')

    def test_one_it_cannot_cover_is_refused_before_anything_is_paid(self):
        self.ltc_wallet.fund_reserve('top-up-1', 1 * COIN)

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_amount=10.0)

        self.assertEqual(str(caught.exception), 'The exchange can take at most 8.09988645 KNF Coin right now')
        self.assertEqual(self.service.list_orders(), [])

    def test_an_empty_reserve_refuses_its_own_direction_only(self):
        self.knf_wallet.fund_reserve('top-up-1', 100 * COIN)

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_amount=10.0)

        self.assertEqual(str(caught.exception), 'The exchange cannot pay out LTC Testnet right now - please try again later')
        other_way = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.assertEqual(other_way['status'], 'awaiting_deposit')

    def test_the_payouts_owed_to_orders_paid_into_count_once_never_twice(self):
        # Owed while the orders wait for their payouts; once paid, the
        # reserve's own balance has paid them — the most it can take stays
        self.ltc_wallet.fund_reserve('top-up-1', 3 * COIN)
        self.locked(10.0, 10.0)

        for moment in ('owed', 'paid'):
            with self.subTest(moment=moment):
                with self.assertRaises(ValidationError) as caught:
                    self.create_order(from_amount=10.0)
                self.assertEqual(str(caught.exception), 'The exchange can take at most 4.29965936 KNF Coin right now')
                self.tick()

        self.assertEqual(len(self.ltc_wallet.payouts), 2)

    def test_the_pages_are_told_what_can_still_be_paid_out(self):
        # 3 tLTC4, less one 10 KNF order's payout and its fee, less the fee
        # of the next payout
        self.ltc_wallet.fund_reserve('top-up-1', 3 * COIN)
        self.locked(10.0)

        self.assertEqual(self.service.rates_snapshot()['capacity'], {KNF: 0.0, LTC: 1.765404})
        ltc = self.service.reserves_snapshot()[1]
        self.assertEqual((ltc['confirmed'], ltc['available']), (3.0, 1.765404))








############################################################
# TestAnOrderTheReserveCannotCoverAnyMore
############################################################
#
# Taken while its reserve could cover it, an order whose
# payout the reserve cannot pay when it is due: its coins go
# back where they came from, and nothing else moves.
############################################################

class TestAnOrderTheReserveCannotCoverAnyMore(ShortfallTestCase):

    def test_its_coins_go_back_to_the_address_they_came_from(self):
        # Both orders fit when they were taken; the first one is paid first
        self.ltc_wallet.fund_reserve('top-up-1', 2 * COIN)
        first, second = self.locked(10.0, 10.0)

        self.tick()
        refunding = self.reload(second)
        self.assertEqual(refunding['status'], 'refunding')
        self.assertEqual(refunding['error'], "The exchange's LTC Testnet reserve could not cover the payout of 1.2345678 LTC Testnet")
        self.assertEqual(self.ltc_wallet.payouts, [('tltc1qstudent1', paid_for(10.0))])

        self.tick()
        self.assertEqual(self.knf_wallet.refunds, [('knf1qfrom-deposit-2', 10 * COIN - REFUND_FEE)])
        self.assertEqual(self.knf_wallet.get_received_sat(second['deposit_scripthash']), 0)

        self.knf_wallet.bury('refund-1')
        self.tick()
        refunded = self.reload(second)
        self.assertEqual(refunded['status'], 'refunded')
        self.assertEqual(refunded['refunds'][0]['recipients'],
                         [{'address': 'knf1qfrom-deposit-2', 'amount': (10 * COIN - REFUND_FEE) / COIN}])
        self.assertTrue(refunded['refunds'][0]['confirmed'])

    def test_nothing_is_paid_out_or_swept_and_the_reserve_is_left_as_it_was(self):
        self.ltc_wallet.fund_reserve('top-up-1', 2 * COIN)
        _first, second = self.locked(10.0, 10.0)
        for _ in range(2):
            self.tick()

        self.assertEqual(self.ltc_wallet.payout_requests, [('tltc1qstudent1', paid_for(10.0)), ('tltc1qstudent2', paid_for(10.0))])
        self.assertEqual(len(self.ltc_wallet.payouts), 1)
        self.assertEqual(self.reserve_sat(self.ltc_wallet), 2 * COIN - paid_for(10.0) - PAYOUT_FEE)
        self.assertIsNone(self.reload(second)['sweep_state'])
        self.assertEqual(self.knf_wallet.built['sweep'], 0)

    def test_a_student_who_sends_more_than_it_can_cover_gets_all_of_it_back(self):
        # Agreed: 10 KNF. Sent from the student's wallet in two payments: 20,
        # worth 2.47 tLTC4 to a reserve holding 2 — one refund, less its fee
        self.ltc_wallet.fund_reserve('top-up-1', 2 * COIN)
        order = self.create_order(from_amount=10.0)
        self.knf_wallet.senders = {'deposit-1': 'knf1qstudent', 'deposit-2': 'knf1qstudent'}
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-1', 12 * COIN, height=99)
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-2', 8 * COIN, height=99)

        for status in ('awaiting_confirmations', 'exchanging', 'sending', 'refunding', 'refunding'):
            self.tick()
            self.assertEqual(self.reload(order)['status'], status)

        self.assertEqual(self.knf_wallet.refunds, [('knf1qstudent', 20 * COIN - (2 * 68 + 31 + 11) * 10)])
        self.assertEqual(self.ltc_wallet.payouts, [])
        self.assertEqual(self.reserve_sat(self.ltc_wallet), 2 * COIN)

    def test_each_payment_goes_back_to_the_address_it_came_from(self):
        self.ltc_wallet.fund_reserve('top-up-1', 2 * COIN)
        order = self.create_order(from_amount=10.0)
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-1', 12 * COIN, height=99)
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-2', 8 * COIN, height=99)

        for _ in range(5):
            self.tick()

        # Each pays the fee of its own coin, the first the fixed part too
        self.assertEqual(self.knf_wallet.refunds, [
            ('knf1qfrom-deposit-1', 12 * COIN - REFUND_FEE),
            ('knf1qfrom-deposit-2', 8 * COIN - (68 + 31) * 10),
        ])








############################################################
# TestOrdersSharingAReserve
############################################################
#
# Several orders paid from one reserve: the change of one
# payout paying the next, and a sweep from the other
# direction refilling it.
############################################################

class TestOrdersSharingAReserve(ShortfallTestCase):

    def test_the_change_of_one_payout_pays_the_next_in_the_same_pass(self):
        self.ltc_wallet.fund_reserve('top-up-1', 3 * COIN)
        first, second = self.locked(10.0, 10.0)

        self.tick()

        self.assertEqual(self.ltc_wallet.payouts, [('tltc1qstudent1', paid_for(10.0)), ('tltc1qstudent2', paid_for(10.0))])
        self.assertEqual([self.reload(first)['tx_send_id'], self.reload(second)['tx_send_id']], ['payout-1', 'payout-2'])
        self.assertEqual(self.reserve_sat(self.ltc_wallet), 3 * COIN - 2 * (paid_for(10.0) + PAYOUT_FEE))

    def test_a_sweep_from_the_other_direction_lets_the_exchange_take_an_order_it_refused(self):
        # The KNF reserve is empty: an LTC -> KNF order is refused
        with self.assertRaises(ValidationError):
            self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')

        # A KNF -> tLTC4 swap runs to its end, its 10 KNF swept into the KNF reserve
        self.ltc_wallet.fund_reserve('top-up-1', 5 * COIN)
        [swap] = self.locked(10.0)
        self.tick()
        self.ltc_wallet.bury('payout-1')
        self.tick()
        self.assertEqual(self.reload(swap)['sweep_state'], 'swept')

        # Taken now, and paid out of the swept coins
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.ltc_wallet.receive(order['deposit_scripthash'], 'ltc-deposit', 1 * COIN, height=99)
        for _ in range(4):
            self.tick()

        self.assertEqual(self.knf_wallet.payouts, [('knf1qstudent', int(round(1.0 / RATE_KNF_TO_LTC * COIN)))])








############################################################
# TestTwoPayoutsOnOneCoin
############################################################
#
# The Electrum server shows a broadcast only at its next
# mempool refresh, so a payout built right after another one
# can pick the reserve coin that one has just spent. The
# network refuses it; the order keeps it, finds it refused
# again at its next try and drops it, and builds a new one
# the try after — each student paid exactly once.
############################################################

class TestTwoPayoutsOnOneCoin(ShortfallTestCase):

    def test_each_student_is_still_paid_exactly_once(self):
        self.ltc_wallet.fund_reserve('top-up-1', 3 * COIN)
        self.ltc_wallet.lagging = True
        first, second = self.locked(10.0, 10.0)

        # The second payout of the pass spends the coin the first one spent
        self.tick()
        refused = self.reload(second)
        self.assertEqual(self.ltc_wallet.payouts, [('tltc1qstudent1', paid_for(10.0))])
        self.assertEqual(refused['tx_send_id'], 'payout-2')   # kept: for all the order knows, it got out
        self.assertIn('txn-mempool-conflict', refused['error'])

        # Its next try, the view refreshed, finds it refused again and drops it ...
        self.ltc_wallet.catch_up()
        self.at(self.start + 30 * 1000)
        self.tick()
        dropped = self.reload(second)
        self.assertIsNone(dropped['tx_send_raw'])
        self.assertEqual(dropped['error'], 'Previous payout attempt conflicted - rebuilding')

        # ... and the one after builds a new payout, out of the first one's change
        self.at(self.start + 60 * 1000)
        self.tick()
        self.assertEqual(self.reload(second)['tx_send_id'], 'payout-3')
        self.assertEqual(self.ltc_wallet.payouts, [('tltc1qstudent1', paid_for(10.0)), ('tltc1qstudent2', paid_for(10.0))])
        self.assertEqual(self.reload(first)['tx_send_id'], 'payout-1')
