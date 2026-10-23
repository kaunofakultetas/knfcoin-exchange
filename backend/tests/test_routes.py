############################################################
#  [*] API tests — the REST surface the frontend consumes
#
#  The routes of app/routes.py through Flask's test client,
#  on a service whose wallets are FakeWallets:
#
#    GET  /api/exchange/health
#    GET  /api/exchange/rates
#    GET  /api/exchange/reserves
#    GET  /api/exchange/orders
#    POST /api/exchange/orders
#    GET  /api/exchange/orders/<id>
#
#  The layer is thin by design, so what it owns is tested
#  here (every field the SPA reads, with its type, is held to
#  the contract in test_api_contract.py): the shapes it
#  answers with, ?limit= read leniently (a missing or broken
#  value is 20, anything else clamped to 1..100), a
#  validation refusal as a 400 carrying the service's own
#  sentence, a reserve that cannot be read as a 503 carrying
#  its own, any other failure as the generic 500 — never a
#  stack trace — and the 404 of an unknown order.
############################################################


from unittest.mock import Mock, patch

from flask import Flask

from app.routes import bp_exchange
from app.service import AMOUNT_LIMITS, KNF, LTC
from app.wallet import COIN

from tests.base import ExchangeTestCase


# A valid new order, as the swap form sends it
ORDER = {'from_asset': KNF, 'to_asset': LTC, 'from_amount': 10.0, 'destination': 'tltc1qstudent'}








############################################################
# ApiTestCase
############################################################
#
# The Flask app around the test service, and orders placed a
# minute apart for the list to sort.
#
# Used by:
#   - every test class below
############################################################

class ApiTestCase(ExchangeTestCase):

    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        app.register_blueprint(bp_exchange)
        app.extensions['exchange_service'] = self.service
        self.client = app.test_client()

    def place_orders(self, count):
        # Orders created a minute apart, oldest first
        ids = []
        for minute in range(count):
            self.at(1_791_105_600_000 + minute * 60_000)
            ids.append(self.create_order()['id'])
        return ids








############################################################
# TestStatusAndPricing
############################################################
#
# The health probe, the rates and the reserves.
############################################################

class TestStatusAndPricing(ApiTestCase):

    def test_health_answers_ok(self):
        response = self.client.get('/api/exchange/health')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'status': 'ok'})

    def test_rates_carry_both_directions_and_the_enforced_limits(self):
        response = self.client.get('/api/exchange/rates')

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(set(body['pairs']), {'KNF Coin->LTC Testnet', 'LTC Testnet->KNF Coin'})
        self.assertEqual(body['limits'], AMOUNT_LIMITS)
        self.assertEqual(body['icons'], {'KNF Coin': '/api/exchange/icons/knf', 'LTC Testnet': '/api/exchange/icons/ltc4'})

    def test_reserves_list_every_chain_in_the_shape_the_page_reads(self):
        response = self.client.get('/api/exchange/reserves')

        self.assertEqual(response.status_code, 200)
        reserves = response.get_json()
        self.assertEqual([reserve['network'] for reserve in reserves], ['knf', 'ltc4'])
        self.assertEqual(set(reserves[0]), {
            'network', 'asset', 'short_name', 'full_name', 'block_explorer', 'icon',
            'address', 'confirmed', 'unconfirmed', 'available', 'error',
        })








############################################################
# TestOrderList
############################################################
#
# The latest orders, newest first, with a lenient ?limit=.
############################################################

class TestOrderList(ApiTestCase):

    def test_the_latest_twenty_newest_first_unless_told_otherwise(self):
        ids = self.place_orders(25)

        listed = [order['id'] for order in self.client.get('/api/exchange/orders').get_json()]

        self.assertEqual(listed, ids[::-1][:20])

    def test_a_limit_is_honoured(self):
        self.place_orders(7)
        self.assertEqual(len(self.client.get('/api/exchange/orders?limit=5').get_json()), 5)

    def test_a_limit_that_is_not_a_whole_number_falls_back_to_twenty(self):
        self.place_orders(25)
        for limit in ('abc', '5.5', ''):
            with self.subTest(limit=limit):
                response = self.client.get(f'/api/exchange/orders?limit={limit}')
                self.assertEqual(response.status_code, 200)
                self.assertEqual(len(response.get_json()), 20)

    def test_a_limit_out_of_range_is_clamped_to_1_and_100(self):
        for limit, used in (('0', 1), ('-3', 1), ('500', 100)):
            with self.subTest(limit=limit):
                with patch.object(self.service, 'list_orders', return_value=[]) as listing:
                    self.client.get(f'/api/exchange/orders?limit={limit}')
                listing.assert_called_once_with(used)

    def test_each_row_carries_every_column_as_stored(self):
        self.place_orders(1)
        row = self.client.get('/api/exchange/orders').get_json()[0]
        for column in ('id', 'from_asset', 'deposit_address', 'deposit_index', 'tx_send_raw', 'sweep_state', 'expires_at'):
            self.assertIn(column, row)
        self.assertEqual((row['from_icon'], row['to_icon']), ('/api/exchange/icons/knf', '/api/exchange/icons/ltc4'))








############################################################
# TestCreateOrder
############################################################
#
# A new order: a 201, a refusal as a 400 carrying the
# service's sentence, anything else as the generic 500.
############################################################

class TestCreateOrder(ApiTestCase):

    def test_a_valid_order_is_created_with_201(self):
        response = self.client.post('/api/exchange/orders', json=ORDER)

        self.assertEqual(response.status_code, 201)
        body = response.get_json()
        self.assertEqual(body, self.service.get_order(body['id']))
        self.assertEqual(body['status'], 'awaiting_deposit')

    def test_a_refusal_is_a_400_carrying_the_services_sentence(self):
        limits = AMOUNT_LIMITS[KNF]
        response = self.client.post('/api/exchange/orders', json={**ORDER, 'from_amount': limits['max'] * 5})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'error': f"Amount must be between {limits['min']} and {limits['max']} KNF Coin"})

    def test_an_order_the_reserve_cannot_cover_is_a_400_carrying_the_most_it_can_take(self):
        self.ltc_wallet.reserve_balance = 1 * COIN

        response = self.client.post('/api/exchange/orders', json=ORDER)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json(), {'error': 'The exchange can take at most 8.09988645 KNF Coin right now'})

    def test_a_reserve_that_cannot_be_read_is_a_503_carrying_the_sentence(self):
        self.ltc_wallet.reserve_balance_sat = Mock(side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out'))

        with self.assertLogs('exchange.service', 'WARNING'):
            response = self.client.post('/api/exchange/orders', json=ORDER)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.get_json(),
                         {'error': 'The exchange cannot check its LTC Testnet reserve right now - please try again in a minute'})

    def test_a_body_that_is_not_json_is_read_as_an_empty_order(self):
        for body, content_type in (('from_asset=KNF', 'application/x-www-form-urlencoded'), ('{broken', 'application/json')):
            with self.subTest(content_type=content_type):
                response = self.client.post('/api/exchange/orders', data=body, content_type=content_type)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.get_json(), {'error': 'Unsupported asset: '})

    def test_any_other_failure_is_a_generic_500_and_is_logged(self):
        with patch.object(self.service, 'create_order', side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable')):
            with self.assertLogs('exchange.api', 'ERROR') as logs:
                response = self.client.post('/api/exchange/orders', json=ORDER)

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {'error': 'Internal error creating order'})
        self.assertIn('Electrum 127.0.0.1:1 unreachable', logs.output[0])

    def test_a_json_list_is_a_generic_500_too(self):
        with self.assertLogs('exchange.api', 'ERROR'):
            response = self.client.post('/api/exchange/orders', json=[ORDER])

        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.get_json(), {'error': 'Internal error creating order'})








############################################################
# TestOneOrder
############################################################
#
# One order as stored, the 404 of an unknown one, and no way
# to change or delete an order through the API.
############################################################

class TestOneOrder(ApiTestCase):

    def test_an_order_is_answered_as_stored(self):
        order = self.create_order()

        response = self.client.get(f"/api/exchange/orders/{order['id']}")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), order)

    def test_an_unknown_order_is_a_404(self):
        response = self.client.get('/api/exchange/orders/NOPE1234')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {'error': 'Not found'})

    def test_orders_cannot_be_changed_or_deleted_through_the_api(self):
        order = self.create_order()
        for method in ('put', 'patch', 'delete'):
            with self.subTest(method=method):
                response = getattr(self.client, method)(f"/api/exchange/orders/{order['id']}", json={'status': 'completed'})
                self.assertEqual(response.status_code, 405)
        self.assertEqual(self.reload(order)['status'], 'awaiting_deposit')
