############################################################
#  [*] Live smoke tests (opt-in: RUN_LIVE=1)
#
#  The RUNNING backend's real answers, held to the same
#  contract the offline suite checks (tests/contract.py): the
#  rates, every reserve with its balance or its reason, the
#  latest orders in the list and on their own pages, the 404
#  of an unknown order — and no key material in any public
#  answer. It is the one check of what the deployed backend
#  really sends, with its real database and Electrum servers
#  behind it.
#
#  Read-only on purpose: no order is created, so nothing turns
#  up in the students' lists. Skipped unless RUN_LIVE=1, so
#  runTests.sh (no network) passes over it. It runs inside
#  the running backend container, where the backend listens
#  on localhost:8000 (LIVE_BASE points it elsewhere) — the
#  command is in tests/README.md.
############################################################


import json
import os
import unittest
import urllib.error
import urllib.request

from tests import contract


# Where the running backend answers
BASE = os.getenv('LIVE_BASE', 'http://localhost:8000')


def fetch(path):
    # The status and the parsed body of one GET — an error status is an
    # answer too, not an exception
    try:
        with urllib.request.urlopen(BASE + path, timeout=30) as response:
            return response.status, json.load(response)
    except urllib.error.HTTPError as error:
        return error.code, json.load(error)








############################################################
# LiveSmokeTests
############################################################
#
# The running backend's answers, held to the contract.
############################################################

@unittest.skipUnless(os.getenv('RUN_LIVE'), 'live smoke is opt-in: set RUN_LIVE=1')
class LiveSmokeTests(unittest.TestCase):

    def test_the_backend_is_up(self):
        self.assertEqual(fetch('/api/exchange/health'), (200, {'status': 'ok'}))

    def test_the_rates_read_as_the_swap_form_expects(self):
        status, rates = fetch('/api/exchange/rates')

        self.assertEqual(status, 200)
        self.assertEqual(contract.rates_problems(rates), [])

    def test_every_reserve_reads_as_the_reserves_page_expects(self):
        status, reserves = fetch('/api/exchange/reserves')

        self.assertEqual(status, 200)
        self.assertEqual(sorted(reserve.get('asset') for reserve in reserves), sorted(contract.ASSETS))
        for reserve in reserves:
            self.assertEqual(contract.reserve_problems(reserve), [], reserve.get('network'))

    def test_the_latest_orders_read_as_the_pages_expect(self):
        status, orders = fetch('/api/exchange/orders?limit=5')

        self.assertEqual(status, 200)
        for order in orders:
            with self.subTest(order=order.get('id')):
                self.assertEqual(contract.order_problems(order), [])

                # The order page fetches the same order on its own (its status
                # may have moved on in between; its shape may not)
                single_status, single = fetch(f"/api/exchange/orders/{order['id']}")
                self.assertEqual(single_status, 200)
                self.assertEqual(single['id'], order['id'])
                self.assertEqual(contract.order_problems(single), [])

    def test_an_unknown_order_is_the_404_the_order_page_shows(self):
        status, body = fetch('/api/exchange/orders/NOPE0000')

        self.assertEqual(status, 404)
        self.assertEqual(contract.error_problems(body), [])

    def test_the_public_answers_carry_no_key_material(self):
        answers = json.dumps([
            fetch(path)[1] for path in ('/api/exchange/rates', '/api/exchange/reserves', '/api/exchange/orders?limit=100')
        ])

        # Nothing shaped like an extended private key...
        self.assertNotRegex(answers, r'[xtv]prv[1-9A-HJ-NP-Za-km-z]{100,}')

        # ...and not the HD seed itself, when this container holds it
        seed = os.getenv('EXCHANGE_PRIVATE_KEY', '').lower().replace('0x', '')
        if len(seed) >= 32:
            self.assertNotIn(seed, answers.lower())
