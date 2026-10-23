############################################################
#  [*] API contract tests — the answers, as the SPA reads them
#
#  The React pages see the backend only through its HTTP
#  answers, and read them field by field (tests/contract.py
#  lists every field with its type). The other test files call
#  the service and the worker directly, so a column renamed,
#  retyped or rescaled on its way out would pass all of them
#  and break the pages in production.
#
#  These tests send real requests through the Flask app —
#  orders taken by the worker's own steps to every status the
#  pages render, refunds included — and hold every answer to
#  that contract: an order at each stage, in the list and on
#  its own page, the new order the swap form opens (or the
#  refusal of one the reserve cannot cover), the rates with
#  what can still be paid out, the reserves, and every failed
#  answer. Amounts are whole coins and times
#  epoch milliseconds; every answer is JSON; the statuses the
#  backend writes and the assets it trades are the ones the
#  pages know. The checks themselves are tested last: each one
#  must catch the break it exists for, or every test above
#  would pass for nothing.
############################################################


import re
import sqlite3
from pathlib import Path
from unittest.mock import patch

from flask import Flask
from werkzeug.exceptions import ServiceUnavailable

from app.config import RATE_KNF_TO_LTC
from app.routes import bp_exchange
from app.service import AMOUNT_LIMITS, ASSET_TO_NETWORK, KNF, LTC
from app.wallet import COIN, ReserveShortfall

from tests import contract
from tests.base import ExchangeTestCase


# The backend's own source, read for the statuses it writes
APP_SOURCE = Path(__file__).resolve().parent.parent / 'app'

# What the swap form sends for a new order (the amount a
# JavaScript number)
SWAP_FORM_REQUEST = {'from_asset': KNF, 'to_asset': LTC, 'from_amount': 10, 'destination': 'tltc1qstudent'}








############################################################
# ContractTestCase
############################################################
#
# The Flask app around the test service, and orders at every
# stage of their life, each reached through the worker's own
# steps: created, seen, confirmed, locked, the payout
# broadcast and then confirmed, a payout that could not get
# out yet, the coins of one the reserve could not cover on
# their way back and then back, expired, failed.
#
# Used by:
#   - every test class below
############################################################

class ContractTestCase(ExchangeTestCase):

    def setUp(self):
        super().setUp()
        self.app = Flask(__name__)
        self.app.register_blueprint(bp_exchange)
        self.app.extensions['exchange_service'] = self.service
        self.client = self.app.test_client()

    def get(self, path):
        response = self.client.get(path)
        self.assertEqual(response.mimetype, 'application/json', path)
        return response.status_code, response.get_json()

    def answer_for(self, order):
        # The order as the order page fetches it — held to the contract
        status, body = self.get(f"/api/exchange/orders/{order['id']}")
        self.assertEqual(status, 200)
        self.assertEqual(contract.order_problems(body), [])
        return body

    def created(self, from_amount=10.0):
        return self.create_order(from_amount=from_amount)

    def seen(self, deposit_sat=10 * COIN, from_amount=10.0):
        order = self.created(from_amount)
        self.knf_wallet.receive(order['deposit_scripthash'], 'deposit-tx', deposit_sat)
        self.worker._check_deposit(self.reload(order))
        return self.reload(order)

    def confirmed(self, deposit_sat=10 * COIN, from_amount=10.0):
        order = self.seen(deposit_sat, from_amount)
        self.knf_wallet.mine('deposit-tx', 101)
        self.knf_wallet.tip_height = 102
        self.worker._check_confirmations(self.reload(order))
        return self.reload(order)

    def locked(self, deposit_sat=10 * COIN, from_amount=10.0):
        order = self.confirmed(deposit_sat, from_amount)
        self.worker._lock_exchange_rate(self.reload(order))
        return self.reload(order)

    def broadcast(self):
        # The payout is out, waiting to confirm on the tLTC4 chain
        order = self.locked()
        self.worker._send_payout(self.reload(order))
        return self.reload(order)

    def paid(self):
        order = self.broadcast()
        self.ltc_wallet.bury('payout-txid')
        self.worker._send_payout(self.reload(order))
        return self.reload(order)

    def payout_pending(self):
        order = self.locked()
        self.ltc_wallet.payout_error = ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')
        self.worker._send_payout(self.reload(order))
        self.ltc_wallet.payout_error = None
        return self.reload(order)

    def refunding(self):
        # The reserve could not cover the payout: the refund is out
        order = self.locked()
        self.ltc_wallet.payout_error = ReserveShortfall('Reserve address has no funds to pay out')
        self.worker._send_payout(self.reload(order))
        self.ltc_wallet.payout_error = None
        self.worker._refund_order(self.reload(order))
        return self.reload(order)

    def refunded(self):
        order = self.refunding()
        self.knf_wallet.bury(order['refunds'][0]['txid'])
        self.worker._refund_order(self.reload(order))
        return self.reload(order)

    def expired(self):
        order = self.created()
        self.at(order['expires_at'] + 1)
        self.worker._check_deposit(order)
        return self.reload(order)

    def failed(self):
        # 1000 sat of KNF pays 123 sat of tLTC4 — below the dust limit; the
        # order is for the smallest amount the exchange takes
        order = self.locked(deposit_sat=1000, from_amount=AMOUNT_LIMITS[KNF]['min'])
        self.worker._send_payout(self.reload(order))
        return self.reload(order)








############################################################
# TestTheOrderPage
############################################################
#
# An order as the order page fetches it: what each stage's
# page relies on, amounts in whole coins and times in epoch
# milliseconds, both directions alike, and the 404 of an
# unknown order.
############################################################

class TestTheOrderPage(ContractTestCase):

    def test_an_order_reads_as_the_pages_expect_at_every_stage(self):
        # Beyond the types, what each stage's page relies on being there
        stages = [
            ('awaiting_deposit', self.created,
             lambda o: o['received_amount'] == 0 and o['tx_deposit_id'] is None and o['locked_rate'] is None),
            ('awaiting_confirmations', self.seen,
             lambda o: o['received_amount'] > 0 and o['tx_deposit_id'] is not None),
            ('exchanging', self.confirmed,
             lambda o: o['confirm_count'] >= o['confirm_target']),
            ('sending', self.locked,
             lambda o: o['locked_rate'] is not None and abs(o['to_amount'] - o['received_amount'] * o['locked_rate']) < 1e-12),
            ('sending', self.payout_pending,
             lambda o: o['error'] is not None),
            ('sending', self.broadcast,
             lambda o: o['tx_send_id'] is not None and o['error'] is None),
            ('completed', self.paid,
             lambda o: o['tx_send_id'] is not None and o['error'] is None and o['refunds'] == []),
            ('refunding', self.refunding,
             lambda o: o['error'] is not None and o['tx_send_id'] is None
             and [refund['confirmed'] for refund in o['refunds']] == [False]),
            ('refunded', self.refunded,
             lambda o: o['error'] is not None and [refund['confirmed'] for refund in o['refunds']] == [True]
             and sum(r['amount'] for r in o['refunds'][0]['recipients']) < o['received_amount']),
            ('expired', self.expired,
             lambda o: o['received_amount'] == 0),
            ('failed', self.failed,
             lambda o: o['error'] is not None),
        ]
        for status, reach, relies_on in stages:
            with self.subTest(stage=reach.__name__):
                body = self.answer_for(reach())
                self.assertEqual(body['status'], status)
                self.assertTrue(relies_on(body), body)

    def test_amounts_are_whole_coins_and_times_epoch_milliseconds(self):
        # The order page multiplies amounts by rates and counts down from
        # expires_at against the browser's clock in milliseconds
        self.at(1_791_105_600_000)
        body = self.answer_for(self.seen(deposit_sat=10 * COIN))

        self.assertEqual(body['from_amount'], 10.0)
        self.assertEqual(body['received_amount'], 10.0)
        self.assertAlmostEqual(body['to_amount'], 10.0 * RATE_KNF_TO_LTC)
        self.assertEqual(body['created_at'], 1_791_105_600_000)
        self.assertEqual(body['expires_at'] - body['created_at'], 30 * 60 * 1000)

    def test_an_ltc_to_knf_order_reads_the_same_way(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')

        body = self.answer_for(order)

        self.assertEqual((body['from_asset'], body['to_asset']), (LTC, KNF))
        self.assertAlmostEqual(body['rate'], 1.0 / RATE_KNF_TO_LTC)

    def test_an_unknown_order_is_the_404_the_order_page_shows(self):
        status, body = self.get('/api/exchange/orders/NOPE1234')

        self.assertEqual(status, 404)
        self.assertEqual(contract.error_problems(body), [])
        self.assertEqual(body, {'error': 'Not found'})








############################################################
# TestTheExchangePage
############################################################
#
# What the swap form and the order list read: the rates, the
# latest orders, the new order the form opens, and every
# failed answer carrying the sentence the form shows — the
# unexpected failures included.
############################################################

class TestTheExchangePage(ContractTestCase):

    def test_the_rates_read_as_the_swap_form_expects(self):
        # Before the worker has read the reserves and after
        status, body = self.get('/api/exchange/rates')
        self.assertEqual(status, 200)
        self.assertEqual(contract.rates_problems(body), [])

        self.service.refresh_capacity()
        _, body = self.get('/api/exchange/rates')
        self.assertEqual(contract.rates_problems(body), [])
        self.assertGreater(body['capacity']['LTC Testnet'], 0)

    def test_the_recent_orders_read_like_the_orders_they_list(self):
        for minute, reach in enumerate((self.created, self.seen, self.locked, self.paid, self.expired, self.created)):
            self.at(1_791_105_600_000 + minute * 60_000)
            reach()

        status, rows = self.get('/api/exchange/orders?limit=5')

        self.assertEqual(status, 200)
        self.assertEqual(len(rows), 5)
        self.assertEqual([row['created_at'] for row in rows], sorted((row['created_at'] for row in rows), reverse=True))
        for row in rows:
            with self.subTest(order=row['id']):
                self.assertEqual(contract.order_problems(row), [])
                self.assertEqual(self.answer_for(row), row)

    def test_the_swap_forms_request_is_accepted_as_it_sends_it(self):
        response = self.client.post('/api/exchange/orders', json=SWAP_FORM_REQUEST)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.mimetype, 'application/json')
        created = response.get_json()
        self.assertEqual(contract.order_problems(created), [])
        # The form opens the new order's page by its id
        self.assertEqual(self.answer_for(created), created)

    def test_a_refusal_carries_the_sentence_the_form_shows(self):
        limits = AMOUNT_LIMITS[KNF]
        response = self.client.post('/api/exchange/orders', json={**SWAP_FORM_REQUEST, 'from_amount': limits['max'] * 5})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(contract.error_problems(response.get_json()), [])
        self.assertEqual(response.get_json()['error'], f"Amount must be between {limits['min']} and {limits['max']} KNF Coin")

    def test_an_order_the_reserve_cannot_cover_is_refused_with_the_sentence_the_form_shows(self):
        self.ltc_wallet.reserve_balance = 0

        response = self.client.post('/api/exchange/orders', json=SWAP_FORM_REQUEST)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(contract.error_problems(response.get_json()), [])
        self.assertEqual(response.get_json()['error'], 'The exchange cannot pay out LTC Testnet right now - please try again later')

    def test_a_reserve_that_cannot_be_read_still_answers_the_sentence_the_form_shows(self):
        with patch.object(self.ltc_wallet, 'reserve_balance_sat', side_effect=ConnectionError('Electrum unreachable')), \
                self.assertLogs('exchange.service', 'WARNING'):
            response = self.client.post('/api/exchange/orders', json=SWAP_FORM_REQUEST)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(contract.error_problems(response.get_json()), [])

    def test_an_unexpected_failure_to_create_still_answers_an_error_body(self):
        with patch.object(self.service, 'create_order', side_effect=ConnectionError('Electrum unreachable')), \
                self.assertLogs('exchange.api', 'ERROR'):
            response = self.client.post('/api/exchange/orders', json=SWAP_FORM_REQUEST)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(contract.error_problems(response.get_json()), [])

    def test_a_read_that_fails_unexpectedly_still_answers_an_error_body(self):
        with patch.object(self.service, 'list_orders', side_effect=sqlite3.OperationalError('database is locked')), \
                self.assertLogs('exchange.api', 'ERROR') as logs:
            response = self.client.get('/api/exchange/orders?limit=5')

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, 'application/json')
        self.assertEqual(contract.error_problems(response.get_json(silent=True)), [])
        self.assertIn('Unexpected error on GET /api/exchange/orders: database is locked', '\n'.join(logs.output))

    def test_an_http_error_a_route_raises_keeps_its_own_status(self):
        with patch.object(self.service, 'get_order', side_effect=ServiceUnavailable()):
            response = self.client.get('/api/exchange/orders/ABCD1234')

        self.assertEqual(response.status_code, 503)








############################################################
# TestTheReservesPage
############################################################
#
# Each reserve as the reserves page reads it: a balance, or
# the reason it has none.
############################################################

class TestTheReservesPage(ContractTestCase):

    def test_each_reserve_reads_as_the_page_expects(self):
        self.knf_wallet.receive('reserve-scripthash', 'top-up-tx', 482150000000, height=90)
        self.ltc_wallet.receive('reserve-scripthash', 'pending-top-up-tx', 40 * COIN)

        status, reserves = self.get('/api/exchange/reserves')

        self.assertEqual(status, 200)
        for reserve in reserves:
            self.assertEqual(contract.reserve_problems(reserve), [], reserve)
        # One card per chain, keyed by its network
        networks = [reserve['network'] for reserve in reserves]
        self.assertEqual(len(networks), len(set(networks)))
        self.assertEqual(sorted(reserve['asset'] for reserve in reserves), sorted(contract.ASSETS))

    def test_a_reserve_without_a_balance_reads_as_its_reason(self):
        self.ltc_wallet.tip_height = 0

        _, reserves = self.get('/api/exchange/reserves')

        ltc = next(reserve for reserve in reserves if reserve['network'] == 'ltc4')
        self.assertEqual(contract.reserve_problems(ltc), [])
        self.assertEqual(ltc['error'], 'Electrum server is still syncing (no chain tip yet)')

    def test_what_a_reserve_still_has_available_is_an_amount_never_below_zero(self):
        # Owed more than it holds, a reserve has nothing available
        self.locked()

        _, reserves = self.get('/api/exchange/reserves')

        ltc = next(reserve for reserve in reserves if reserve['network'] == 'ltc4')
        self.assertEqual(contract.reserve_problems(ltc), [])
        self.assertEqual(ltc['available'], 0)








############################################################
# TestTheSharedVocabulary
############################################################
#
# The status strings the backend writes and the asset labels
# it trades, read from its source: the ones the pages know.
############################################################

class TestTheSharedVocabulary(ContractTestCase):

    def test_every_status_the_backend_writes_is_one_the_pages_know(self):
        # The two modules that write orders, both ways they write a status:
        # in an update's dict, or set on it
        written = set()
        for module in ('service.py', 'worker.py'):
            source = (APP_SOURCE / module).read_text()
            written.update(re.findall(r"(?:'status':\s*|\['status'\]\s*=\s*)'(\w+)'", source))

        self.assertEqual(written, set(contract.STATUSES))

    def test_the_assets_traded_are_the_labels_the_pages_show(self):
        self.assertEqual(sorted(ASSET_TO_NETWORK), sorted(contract.ASSETS))
        self.assertEqual(sorted(AMOUNT_LIMITS), sorted(contract.ASSETS))








############################################################
# TestTheChecksThemselves
############################################################
#
# Each checker of tests/contract.py must catch the break it
# exists for, or every test above would pass for nothing.
############################################################

class TestTheChecksThemselves(ContractTestCase):

    def test_an_order_with_a_renamed_retyped_or_rescaled_field_is_caught(self):
        good = self.answer_for(self.seen())
        breaks = {
            'a renamed field': ({k: v for k, v in good.items() if k != 'received_amount'} | {'received': 10.0},
                                'order lacks received_amount'),
            'an amount as text': (good | {'from_amount': '10.0'}, 'order.from_amount should be a number'),
            'a time in seconds': (good | {'expires_at': good['expires_at'] // 1000}, 'order.expires_at should be epoch milliseconds'),
            'an unknown status': (good | {'status': 'cancelled'}, 'order.status should be a known status'),
            'no refunds list': (good | {'refunds': None}, 'order.refunds should be a list'),
            'a refund without its txid': (good | {'refunds': [{'confirmed': False, 'created_at': good['created_at'],
                                                               'recipients': []}]},
                                          'order.refunds[0] lacks txid'),
            'a refund confirmed as text': (good | {'refunds': [{'txid': 'aa', 'confirmed': 'yes', 'created_at': good['created_at'],
                                                                'recipients': []}]},
                                           'order.refunds[0].confirmed should be true or false'),
            'a recipient paid in satoshis as text': (
                good | {'refunds': [{'txid': 'aa', 'confirmed': False, 'created_at': good['created_at'],
                                     'recipients': [{'address': 'knf1qstudent', 'amount': '999998900'}]}]},
                'order.refunds[0].recipients[0].amount should be a positive number'),
            'an unknown asset': (good | {'from_asset': 'KNF'}, 'order.from_asset should be an asset label'),
            'a count with a fraction': (good | {'confirm_count': 1.5}, 'order.confirm_count should be an integer'),
            'a logo by file path': (good | {'to_icon': '/config/icons/ltc4.svg'}, 'order.to_icon should be a logo URL or null'),
            'not an object': ([good], 'order is not an object'),
        }
        self.assertEqual(contract.order_problems(good), [])
        for label, (broken, problem) in breaks.items():
            with self.subTest(label):
                problems = contract.order_problems(broken)
                self.assertTrue(any(p.startswith(problem) for p in problems), problems)

    def test_a_reserve_showing_both_or_neither_a_balance_and_a_reason_is_caught(self):
        _, reserves = self.get('/api/exchange/reserves')
        good = reserves[0]
        self.assertEqual(contract.reserve_problems(good), [])

        both = good | {'error': 'Electrum server is still syncing (no chain tip yet)'}
        neither = good | {'confirmed': None, 'unconfirmed': None}
        nothing_available = good | {'available': None}
        self.assertEqual(contract.reserve_problems(both), ['reserve knf has an error but still a balance'])
        self.assertEqual(contract.reserve_problems(neither), ['reserve knf has no error but no balance either'])
        self.assertEqual(contract.reserve_problems(nothing_available), ['reserve knf has no error but no balance either'])

    def test_rates_missing_a_direction_crossed_limits_or_a_logo_are_caught(self):
        _, good = self.get('/api/exchange/rates')
        one_way = good | {'pairs': {'KNF Coin->LTC Testnet': RATE_KNF_TO_LTC}}
        crossed = good | {'limits': good['limits'] | {'KNF Coin': {'min': 1000, 'max': 0.001}}}
        one_logo = good | {'icons': {'KNF Coin': '/api/exchange/icons/knf'}}
        no_logos = {key: value for key, value in good.items() if key != 'icons'}
        a_debt = good | {'capacity': {'KNF Coin': -1.0, 'LTC Testnet': None}}
        no_capacity = {key: value for key, value in good.items() if key != 'capacity'}

        self.assertEqual(contract.rates_problems(good), [])
        for broken in (one_way, crossed, one_logo, no_logos, a_debt, no_capacity):
            with self.subTest(broken=broken):
                self.assertEqual(len(contract.rates_problems(broken)), 1)
        # A coin without a logo file is no break: the page draws its dot
        self.assertEqual(contract.rates_problems(good | {'icons': {'KNF Coin': None, 'LTC Testnet': None}}), [])

    def test_a_failed_answer_without_its_sentence_is_caught(self):
        for body in ({'message': 'Not found'}, {'error': ''}, {'error': 'Not found', 'code': 404}, None):
            with self.subTest(body=body):
                self.assertEqual(len(contract.error_problems(body)), 1)
