############################################################
#  [*] Shared test scaffolding
#
#  ExchangeTestCase gives every test a scratch SQLite database
#  (DB_PATH points at a temp file, resolved at call time by
#  app.database), a scratch logo folder holding a logo for
#  both chains, and an ExchangeService whose wallets are
#  FakeWallets — or CoinWallets, for a test class that asks
#  for them — so the full service + worker stack runs with
#  zero network access. Its helpers create and fund orders,
#  freeze the service clock and run single passes of the real
#  worker loop.
#
#  known_bug pins a defect a test found without fixing it
#  here: the test runs as an expected failure, so the suite
#  stays green while the bug is on record, and turns red
#  ("unexpected success") the day the bug is fixed — a pin
#  cannot outlive its bug. unittest -v prints the description
#  under the test's name.
#
#  Used by:
#    - every test module
############################################################


import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.chains import ChainDefinition
from app.database import init_db
from app.service import ExchangeService, KNF, LTC

from tests.fakes import FakeWallet


# The app's two chains as the tests run them: the same names,
# prefixes and confirmation targets, Electrum endpoints that are
# never contacted
TEST_CHAINS = {
    'knf': ChainDefinition(
        short_name='KNF',
        full_name='KNF Coin',
        network='mainnet',
        bech32_hrp='knf',
        electrum_server='127.0.0.1:1',   # never contacted: wallets are fakes
        block_explorer='/explorer',
        confirm_target=2,
    ),
    'ltc4': ChainDefinition(
        short_name='tLTC4',
        full_name='Litecoin Testnet4',
        network='testnet',
        bech32_hrp='tltc',
        electrum_server='127.0.0.1:1',
        block_explorer='https://example.org',
        confirm_target=2,
    ),
}








############################################################
# ExchangeTestCase
############################################################
#
# A fresh scratch database and service per test, its two
# wallets (self.knf_wallet, self.ltc_wallet) and the service's
# own worker at hand, and the logo folder (self.icons_dir)
# holding a logo for both chains — plus the helpers the tests
# share: an order created as the swap form sends it, coins put
# on its deposit address, the order re-read, the service clock
# frozen, and one pass of the worker loop. The wallets are
# FakeWallets; a test class whose orders need their coins to
# move sets wallet_class to CoinWallet.
#
# Used by:
#   - test_service, test_worker, test_reorg, test_lifecycle,
#     test_refunds, test_routes, test_api_contract, test_app
#   - test_reserve_shortfall, test_several_deposits — with
#     CoinWallets
############################################################

class ExchangeTestCase(unittest.TestCase):

    wallet_class = FakeWallet

    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        os.environ['DB_PATH'] = self.db_path
        init_db()

        # The coin logos the answers advertise: one for each chain
        self.icons_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.icons_dir)
        for network in TEST_CHAINS:
            with open(os.path.join(self.icons_dir, f'{network}.svg'), 'w') as logo:
                logo.write(f'<svg xmlns="http://www.w3.org/2000/svg"><title>{network}</title></svg>')
        icons = patch('app.icons.ICONS_DIR', self.icons_dir)
        icons.start()
        self.addCleanup(icons.stop)

        self.service = ExchangeService(TEST_CHAINS)

        # Pre-populate the lazy wallet cache with fakes so wallet_for()
        # never constructs a real ExchangeWallet (which needs keys + TLS).
        self.knf_wallet = self.wallet_class(hrp='knf')
        self.ltc_wallet = self.wallet_class(hrp='tltc')
        self.service.wallets = {'knf': self.knf_wallet, 'ltc4': self.ltc_wallet}

        self.worker = self.service.worker

    def tearDown(self):
        # The database, and the write-ahead log's side files when a
        # connection somewhere still held them open
        for name in (self.db_path, self.db_path + '-wal', self.db_path + '-shm'):
            if os.path.exists(name):
                os.unlink(name)
        os.environ.pop('DB_PATH', None)

    # --- Helpers ----------------------------------------------------------------

    def create_order(self, from_asset=KNF, to_asset=LTC, from_amount=10.0,
                     destination='tltc1qstudent'):
        return self.service.create_order({
            'from_asset':  from_asset,
            'to_asset':    to_asset,
            'from_amount': from_amount,
            'destination': destination,
        })

    def fund_deposit(self, order, amount_sat, height=0, tx_hash='deposit-tx'):
        # Coins arriving on the order's deposit address, seen at `height`
        # (0 = still in the mempool)
        wallet = self.service.wallet_for_asset(order['from_asset'])
        scripthash = order['deposit_scripthash']
        wallet.unspent.setdefault(scripthash, []).append({
            'tx_hash': tx_hash, 'tx_pos': 0, 'height': height, 'value': amount_sat,
        })
        wallet.history.setdefault(scripthash, []).append({
            'tx_hash': tx_hash, 'height': height,
        })

    def reload(self, order):
        return self.service.get_order(order['id'])

    def wallet_of(self, order):
        # The wallet of the chain the order's deposit lives on
        return self.service.wallet_for_asset(order['from_asset'])

    def at(self, moment_ms):
        # Freezes the service clock — every timestamp the service and the
        # worker write or compare — at the given epoch milliseconds
        self.service.now = lambda: moment_ms

    def tick(self):
        # One pass of the real worker loop, as its daemon thread runs it:
        # every active order dispatched, then the sweep — stopped where the
        # loop would sleep until the next pass
        self.worker.stop_flag = False
        stop = lambda _seconds: setattr(self.worker, 'stop_flag', True)
        with patch('app.worker.time.sleep', side_effect=stop):
            self.worker._loop()








############################################################
# known_bug
############################################################
#
# Pins a defect a test found: the test runs as an expected
# failure carrying the description, which unittest -v prints
# under its name, and fails the run the day the bug is fixed.
#
# Used by:
#   - no test at the moment — every bug pinned so far has been
#     fixed; it stays for the next one
############################################################

def known_bug(description):
    def pin(test):
        test.__doc__ = f'PINNED KNOWN BUG: {description}'
        return unittest.expectedFailure(test)
    return pin
