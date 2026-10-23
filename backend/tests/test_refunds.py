############################################################
#  [*] Refund tests — coins sent back where they came from
#
#  The worker's refund step on FakeWallets. An order that
#  could not go through (refunding), and an order that is done
#  but finds coins on its address its payout did not pay for,
#  both send them back: each coin to the script that paid its
#  transaction's first input, all of them in one refund that
#  is persisted before it is broadcast and then followed to
#  the depth a deposit needs:
#
#    - a refunding order sends every coin back and is refunded
#      once the refund confirms — or fails when not one coin
#      can go back (too few of them, or no sender to find); a
#      server that does not hand out a deposit's transaction
#      holds the refund back, tried again after a back-off,
#      and never fails it
#    - only confirmed coins go back; coins still confirming
#      keep a refunding order waiting for them
#    - a refund persisted before a crash goes out again, never
#      a second one; one the network lost is broadcast again,
#      the very same; one it refuses for good is dropped, its
#      coins free to go back anew; one it already knows is
#      waited for; an unexplained failure surfaces
#    - an order that is done sends back only the coins its
#      payout did not pay for, never twice, looked at once a
#      minute for a day after its deadline; one completed
#      before its coins were tracked sends nothing back; a
#      failed one that does send coins back is refunding again
#    - every order answer lists its refunds, oldest first,
#      with who each one pays what
############################################################


from app.wallet import COIN
from app.worker import REFUND_RETRY_MS

from tests.base import ExchangeTestCase


# What a one-input refund costs the coins it sends, at the 10 sat/vbyte
# the tests run with
REFUND_FEE = 1100

# Why the orders here could not go through
REASON = "The exchange's LTC Testnet reserve could not cover the payout of 1.2345678 LTC Testnet"

# What a server whose node keeps no transaction index answers when asked for
# a confirmed transaction (the same while the index is still being built)
NOT_INDEXED = ("Electrum error: {'code': 2, 'message': \"daemon error: DaemonError({'code': -5, 'message': "
               "'No such mempool transaction. Use -txindex or provide a block hash to enable blockchain "
               "transaction queries. Use gettransaction for wallet transactions.'})\"}")

# A day, and a minute, in milliseconds
DAY_MS = 24 * 60 * 60 * 1000
MINUTE_MS = 60 * 1000








############################################################
# RefundTestCase
############################################################
#
# Orders in the states that send coins back, their deposits
# confirmed at the fake's tip of 100: one refunding, one that
# is done with the coins its payout paid for named — and the
# refund step run on each, as the loop runs it.
#
# Used by:
#   - every test class below
############################################################

class RefundTestCase(ExchangeTestCase):

    def setUp(self):
        super().setUp()
        self.start = self.service.now()
        self.at(self.start)

    def refunding(self, *coins):
        # An order that could not go through, holding the given coins (tx
        # hash, satoshis, height); one confirmed 10 KNF deposit by default
        order = self.create_order()
        for tx_hash, value, height in coins or (('deposit-tx', 10 * COIN, 99),):
            self.fund_deposit(order, value, height=height, tx_hash=tx_hash)
        received = sum(value for _tx, value, _height in coins or (('deposit-tx', 10 * COIN, 99),))
        self.service.update_order(order['id'], {'status': 'refunding', 'error': REASON, 'received_amount': received / COIN})
        return self.reload(order)

    def done(self, status='completed', paid_coins='["deposit-tx:0"]'):
        # An order that is done, its 10 KNF deposit on the address
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN, height=99)
        self.service.update_order(order['id'], {'status': status, 'received_amount': 10.0, 'paid_coins': paid_coins})
        return self.reload(order)

    def refund_step(self, order):
        self.worker._refund_order(self.reload(order))
        return self.reload(order)

    def recipients(self, order):
        return [refund['recipients'] for refund in self.reload(order)['refunds']]








############################################################
# TestARefundingOrder
############################################################
#
# refunding: every coin back where it came from, the order
# refunded once the refund confirms, failed when nothing can
# go back.
############################################################

class TestARefundingOrder(RefundTestCase):

    def test_every_coin_goes_back_to_where_it_came_from_in_one_refund(self):
        # Two payments from two wallets; each pays the fee of its own coin,
        # the first the fixed part too
        order = self.refunding(('deposit-tx', 6 * COIN, 99), ('top-up-tx', 4 * COIN, 99))

        updated = self.refund_step(order)

        self.assertEqual(updated['status'], 'refunding')
        self.assertEqual(self.knf_wallet.broadcasts, ['refund-1-raw'])
        self.assertEqual(updated['refunds'], [{
            'txid': 'refund-1', 'confirmed': False, 'created_at': self.start,
            'recipients': [
                {'address': 'knf1qfrom-deposit-tx', 'amount': (6 * COIN - REFUND_FEE) / COIN},
                {'address': 'knf1qfrom-top-up-tx', 'amount': (4 * COIN - 990) / COIN},
            ],
        }])

    def test_once_the_refund_has_confirmed_as_deep_as_a_deposit_the_order_is_refunded(self):
        order = self.refunding()
        self.refund_step(order)

        self.knf_wallet.bury('refund-1', confirmations=1)
        self.assertEqual(self.refund_step(order)['status'], 'refunding')

        self.knf_wallet.bury('refund-1', confirmations=2)
        refunded = self.refund_step(order)
        self.assertEqual(refunded['status'], 'refunded')
        self.assertEqual(refunded['error'], REASON)
        self.assertTrue(refunded['refunds'][0]['confirmed'])
        self.assertEqual(self.knf_wallet.broadcasts, ['refund-1-raw'])

    def test_only_confirmed_coins_go_back_and_the_rest_keep_the_order_waiting(self):
        # A top-up still in the mempool could yet be replaced
        order = self.refunding(('deposit-tx', 10 * COIN, 99), ('top-up-tx', 2 * COIN, 0))
        self.refund_step(order)
        self.assertEqual(self.recipients(order), [[{'address': 'knf1qfrom-deposit-tx', 'amount': (10 * COIN - REFUND_FEE) / COIN}]])

        self.knf_wallet.bury('refund-1')
        self.assertEqual(self.refund_step(order)['status'], 'refunding')

        self.knf_wallet.mine('top-up-tx', 100)
        self.refund_step(order)
        self.knf_wallet.bury('refund-2')
        refunded = self.refund_step(order)

        self.assertEqual(refunded['status'], 'refunded')
        self.assertEqual(self.recipients(order)[1], [{'address': 'knf1qfrom-top-up-tx', 'amount': (2 * COIN - REFUND_FEE) / COIN}])

    def test_coins_too_few_to_send_back_fail_the_order(self):
        # 1000 sat: a refund's 1100 sat fee would eat all of it
        order = self.refunding(('dust-tx', 1000, 99))

        failed = self.refund_step(order)

        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error'], REASON)
        self.assertEqual(failed['refunds'], [])
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_coins_whose_sender_cannot_be_found_stay_and_fail_the_order(self):
        # A coinbase, or a transaction the server cannot read
        self.knf_wallet.senders = {'deposit-tx': None}
        order = self.refunding()

        self.assertEqual(self.refund_step(order)['status'], 'failed')
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_a_server_that_does_not_hand_out_the_deposit_holds_the_refund_back_and_never_fails_it(self):
        # A node without a transaction index refuses every confirmed one
        self.knf_wallet.senders = {'deposit-tx': RuntimeError(NOT_INDEXED)}
        order = self.refunding()

        with self.assertRaises(RuntimeError):
            self.refund_step(order)

        self.assertEqual(self.reload(order)['status'], 'refunding')
        self.assertEqual(self.knf_wallet.broadcasts, [])

    def test_the_refund_held_back_is_tried_again_after_a_back_off_and_goes_out(self):
        asked = []
        found = self.knf_wallet.sender_of
        self.knf_wallet.sender_of = lambda tx_hash: asked.append(tx_hash) or found(tx_hash)
        self.knf_wallet.senders = {'deposit-tx': RuntimeError(NOT_INDEXED)}
        order = self.refunding()
        with self.assertRaises(RuntimeError):
            self.refund_step(order)

        # Not asked again before the back-off is over
        self.at(self.start + REFUND_RETRY_MS - 1)
        self.refund_step(order)
        self.assertEqual(asked, ['deposit-tx'])

        # The server hands it out now: the coins go back
        self.knf_wallet.senders = {}
        self.at(self.start + REFUND_RETRY_MS)
        self.refund_step(order)
        self.assertEqual(asked, ['deposit-tx', 'deposit-tx'])
        self.assertEqual(self.recipients(order), [[{'address': 'knf1qfrom-deposit-tx', 'amount': (10 * COIN - REFUND_FEE) / COIN}]])

    def test_a_sender_once_found_is_not_asked_of_the_chain_again(self):
        # A coin too small to go back is looked at on every step while a
        # top-up confirms; its sender is asked once
        asked = []
        found = self.knf_wallet.sender_of
        self.knf_wallet.sender_of = lambda tx_hash: asked.append(tx_hash) or found(tx_hash)
        order = self.refunding(('dust-tx', 1000, 99), ('top-up-tx', 2 * COIN, 0))

        for _ in range(3):
            self.refund_step(order)

        self.assertEqual(asked, ['dust-tx'])
        self.assertEqual(self.reload(order)['status'], 'refunding')








############################################################
# TestFollowingARefund
############################################################
#
# A refund after it was signed: persisted before a crash,
# lost by the network, refused for good, already known, or
# not answered at all.
############################################################

class TestFollowingARefund(RefundTestCase):

    def test_a_refund_persisted_before_a_crash_goes_out_again_never_a_second_one(self):
        order = self.refunding()
        self.knf_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')
        with self.assertRaises(ConnectionError):
            self.refund_step(order)
        self.assertEqual([refund['txid'] for refund in self.reload(order)['refunds']], ['refund-1'])

        # The next try, once the back-off is over
        self.knf_wallet.broadcast_error = None
        self.at(self.start + REFUND_RETRY_MS)
        self.refund_step(order)

        self.assertEqual(self.knf_wallet.broadcasts, ['refund-1-raw'])
        self.assertEqual(self.knf_wallet.refunds_built, 1)

    def test_a_refund_the_network_lost_is_broadcast_again_the_very_same(self):
        order = self.refunding()
        self.refund_step(order)
        self.knf_wallet.drop('refund-1')

        self.assertEqual(self.refund_step(order)['status'], 'refunding')

        self.assertEqual(self.knf_wallet.broadcasts, ['refund-1-raw', 'refund-1-raw'])
        self.assertEqual(self.knf_wallet.refunds_built, 1)

    def test_a_refund_refused_for_good_is_dropped_and_its_coins_go_back_anew(self):
        order = self.refunding()
        self.refund_step(order)
        self.knf_wallet.drop('refund-1')
        self.knf_wallet.broadcast_error = RuntimeError('Electrum error: bad-txns-inputs-missingorspent')

        with self.assertLogs('exchange.worker', 'WARNING'):
            self.assertFalse(self.worker._follow_refunds(self.reload(order), self.knf_wallet))
        self.assertEqual(self.reload(order)['refunds'], [])

        self.knf_wallet.broadcast_error = None
        self.refund_step(order)
        self.assertEqual([refund['txid'] for refund in self.reload(order)['refunds']], ['refund-2'])

    def test_a_refund_the_network_already_knows_is_waited_for(self):
        for answer in ('transaction already in block chain', 'txn-already-known', 'Duplicate transaction'):
            with self.subTest(answer=answer):
                order = self.refunding()
                self.refund_step(order)
                self.knf_wallet.drop(self.reload(order)['refunds'][0]['txid'])
                self.knf_wallet.broadcast_error = RuntimeError(f'Electrum error: {answer}')

                self.assertTrue(self.worker._follow_refunds(self.reload(order), self.knf_wallet))
                self.assertEqual(len(self.reload(order)['refunds']), 1)
                self.knf_wallet.broadcast_error = None

    def test_an_unexplained_failure_to_rebroadcast_surfaces(self):
        order = self.refunding()
        self.refund_step(order)
        self.knf_wallet.drop('refund-1')
        self.knf_wallet.broadcast_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')

        with self.assertRaises(ConnectionError):
            self.refund_step(order)
        self.assertEqual(len(self.reload(order)['refunds']), 1)








############################################################
# TestCoinsOnAnOrderThatIsDone
############################################################
#
# Coins an order that is done did not pay for: sent back,
# once a minute, for a day after its deadline.
############################################################

class TestCoinsOnAnOrderThatIsDone(RefundTestCase):

    def test_a_completed_order_sends_back_only_the_coins_its_payout_did_not_pay_for(self):
        order = self.done()
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')

        self.tick()

        self.assertEqual(self.recipients(order), [[{'address': 'knf1qfrom-late-tx', 'amount': (5 * COIN - REFUND_FEE) / COIN}]])
        self.assertEqual(self.reload(order)['status'], 'completed')

    def test_its_refund_is_followed_to_its_confirmation_and_never_doubled(self):
        order = self.done()
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')
        self.tick()
        self.knf_wallet.bury('refund-1')

        self.at(self.start + MINUTE_MS)
        self.tick()

        self.assertTrue(self.reload(order)['refunds'][0]['confirmed'])
        self.assertEqual(self.knf_wallet.refunds_built, 1)

    def test_a_failed_or_refunded_order_sends_back_what_reaches_its_address_later(self):
        # Failed says not one coin went back: once one has, it is refunding
        for status, then in (('failed', 'refunding'), ('refunded', 'refunded')):
            with self.subTest(status=status):
                order = self.done(status=status, paid_coins=None)
                self.knf_wallet.unspent[order['deposit_scripthash']] = []
                self.fund_deposit(order, 3 * COIN, height=99, tx_hash=f'late-{status}-tx')

                self.worker._late_check_due = 0
                self.tick()

                self.assertEqual(self.recipients(order),
                                 [[{'address': f'knf1qfrom-late-{status}-tx', 'amount': (3 * COIN - REFUND_FEE) / COIN}]])
                self.assertEqual(self.reload(order)['status'], then)

    def test_a_failed_order_whose_coins_do_go_back_after_all_ends_refunded(self):
        # Failed while its chain's server refused to hand out the deposit:
        # the coins are still on the address, and go once it hands it out
        self.knf_wallet.senders = {'deposit-tx': RuntimeError(NOT_INDEXED)}
        order = self.done(status='failed', paid_coins=None)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'failed')

        self.knf_wallet.senders = {}
        self.at(self.start + MINUTE_MS)
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'refunding')
        self.assertEqual(self.recipients(order), [[{'address': 'knf1qfrom-deposit-tx', 'amount': (10 * COIN - REFUND_FEE) / COIN}]])

        self.knf_wallet.bury('refund-1')
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'refunded')

    def test_a_failed_order_whose_refund_already_confirmed_catches_up_to_refunded(self):
        # Sent back and confirmed by a worker that left failed orders failed:
        # the first look moves it on, the next pass finds nothing left to do
        order = self.done(status='failed', paid_coins=None)
        self.worker._send_back_unpaid(self.reload(order), self.knf_wallet)
        self.knf_wallet.bury('refund-1')
        self.worker._follow_refunds(self.reload(order), self.knf_wallet)
        self.assertEqual(self.reload(order)['status'], 'failed')
        self.assertTrue(self.reload(order)['refunds'][0]['confirmed'])

        self.tick()
        self.assertEqual(self.reload(order)['status'], 'refunding')
        self.tick()
        self.assertEqual(self.reload(order)['status'], 'refunded')
        self.assertEqual(self.knf_wallet.refunds_built, 1)

    def test_coins_are_looked_at_once_a_minute_not_every_pass(self):
        order = self.done()
        self.tick()
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')

        self.at(self.start + 30 * 1000)
        self.tick()
        self.assertEqual(self.reload(order)['refunds'], [])

        self.at(self.start + MINUTE_MS)
        self.tick()
        self.assertEqual(len(self.reload(order)['refunds']), 1)

    def test_a_day_after_its_deadline_an_order_is_no_longer_watched(self):
        order = self.done()
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')

        self.at(order['expires_at'] + DAY_MS + 1)
        self.tick()

        self.assertEqual(self.reload(order)['refunds'], [])

    def test_an_order_completed_before_its_coins_were_tracked_sends_nothing_back(self):
        # All of the coins on its address were paid for
        order = self.done(paid_coins=None)
        self.fund_deposit(order, 5 * COIN, height=99, tx_hash='late-tx')

        self.tick()

        self.assertEqual(self.reload(order)['refunds'], [])
        self.assertEqual(self.knf_wallet.broadcasts, [])








############################################################
# TestRefundsInTheAnswer
############################################################
#
# Every order answer lists its refunds, oldest first, with
# who each one pays what.
############################################################

class TestRefundsInTheAnswer(RefundTestCase):

    def test_an_order_without_refunds_lists_none(self):
        self.assertEqual(self.create_order()['refunds'], [])

    def test_its_refunds_are_listed_oldest_first(self):
        order = self.refunding(('deposit-tx', 10 * COIN, 99), ('top-up-tx', 2 * COIN, 0))
        self.refund_step(order)
        self.at(self.start + MINUTE_MS)
        self.knf_wallet.mine('top-up-tx', 100)
        self.refund_step(order)

        refunds = self.service.list_orders()[0]['refunds']

        self.assertEqual([(refund['txid'], refund['created_at']) for refund in refunds],
                         [('refund-1', self.start), ('refund-2', self.start + MINUTE_MS)])

    def test_a_script_the_exchange_cannot_name_is_listed_without_an_address(self):
        # A legacy address: the refund still pays its script
        self.knf_wallet.address_of = lambda script: None
        order = self.refunding()

        self.refund_step(order)

        self.assertEqual(self.recipients(order), [[{'address': None, 'amount': (10 * COIN - REFUND_FEE) / COIN}]])

    def test_a_refund_changes_the_orders_update_time(self):
        # The order page polls the order, not its refunds
        order = self.refunding()
        self.at(self.start + 5000)

        self.assertEqual(self.refund_step(order)['updated_at'], self.start + 5000)
