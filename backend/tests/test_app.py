############################################################
#  [*] App tests — create_app, the entry point's wiring
#
#  main.create_app as the container starts it, with the two
#  steps that would reach the network held back (deriving and
#  logging the reserve addresses, starting the worker thread —
#  both recorded instead): a bad configuration stops it before
#  anything else happens; otherwise it prepares the database,
#  builds the exchange service, logs the reserves, starts the
#  worker, keeps the service in app.extensions and serves the
#  exchange API and the coin logos. Behind the Caddy endpoint
#  it trusts exactly one proxy hop for the client's address,
#  scheme, host and path prefix.
############################################################


import importlib
import os
import sqlite3
from unittest.mock import patch

from flask import request

from app.service import ExchangeService

from tests.base import ExchangeTestCase


# main configures the root logger when imported; the tests keep their own
with patch('logging.basicConfig'):
    main = importlib.import_module('main')








############################################################
# TestCreateApp
############################################################
#
# create_app as the container starts it, with a throwaway
# seed in the environment and the two steps that would reach
# the network — starting the worker and logging the reserve
# addresses — recorded instead of run.
############################################################

class TestCreateApp(ExchangeTestCase):

    def setUp(self):
        super().setUp()
        seed = patch.dict(os.environ, {'EXCHANGE_PRIVATE_KEY': 'ab' * 32})
        seed.start()
        self.addCleanup(seed.stop)
        self.start_worker = self.held_back('start_worker')
        self.log_reserve_addresses = self.held_back('log_reserve_addresses')

    def held_back(self, step):
        # The service step is recorded instead of run
        change = patch.object(ExchangeService, step)
        self.addCleanup(change.stop)
        return change.start()

    def test_a_bad_configuration_stops_it_before_anything_else(self):
        del os.environ['EXCHANGE_PRIVATE_KEY']

        with self.assertRaises(SystemExit):
            main.create_app()

        self.start_worker.assert_not_called()
        self.log_reserve_addresses.assert_not_called()

    def test_it_prepares_the_database(self):
        fresh = os.path.join(os.path.dirname(self.db_path), f'fresh-{os.getpid()}-{id(self)}.db')
        self.addCleanup(lambda: os.path.exists(fresh) and os.unlink(fresh))
        os.environ['DB_PATH'] = fresh

        main.create_app()

        with sqlite3.connect(fresh) as conn:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertEqual(tables, {'orders', 'refunds', 'meta'})

    def test_it_builds_the_service_logs_the_reserves_and_starts_the_worker(self):
        app = main.create_app()

        self.assertIsInstance(app.extensions['exchange_service'], ExchangeService)
        self.log_reserve_addresses.assert_called_once_with()
        self.start_worker.assert_called_once_with()

    def test_it_serves_the_exchange_api(self):
        response = main.create_app().test_client().get('/api/exchange/health')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {'status': 'ok'})

    def test_it_serves_the_coin_logos(self):
        response = main.create_app().test_client().get('/api/exchange/icons/knf')
        self.addCleanup(response.close)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')

    def test_it_trusts_exactly_one_proxy_hop(self):
        app = main.create_app()

        @app.route('/whoami')
        def whoami():
            return {'address': request.remote_addr, 'scheme': request.scheme,
                    'host': request.host, 'prefix': request.script_root}

        response = app.test_client().get('/whoami', headers={
            'X-Forwarded-For': '198.51.100.1, 203.0.113.7',
            'X-Forwarded-Proto': 'https',
            'X-Forwarded-Host': 'knfcoin.knf.vu.lt',
            'X-Forwarded-Prefix': '/exchange',
        })

        self.assertEqual(response.get_json(), {
            'address': '203.0.113.7', 'scheme': 'https', 'host': 'knfcoin.knf.vu.lt', 'prefix': '/exchange',
        })
