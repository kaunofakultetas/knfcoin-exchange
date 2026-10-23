############################################################
#  [*] Configuration tests — the knobs and the startup check
#
#  app/config.py reads every knob from the environment once,
#  at import, falling back to the classroom defaults — the
#  mounted configuration folder to the docker mount, or the
#  repository's own; the tests re-import it under a controlled
#  environment and put it back afterwards. validate() is the
#  fail-fast gate create_app runs before anything else: no
#  seed, a seed that is not hex or shorter than 128 bits (the
#  wallet would pad it with zeros into a guessable HD seed), a
#  rate or fee rate that is not positive, or a coins file that
#  configures other chains than the exchange trades stops the
#  start with a sentence naming the fault. (The coins file's
#  own entries are tested in test_chains.py.)
############################################################


import importlib
import os
import unittest
from unittest.mock import patch

from app import config
from app.chains import ChainDefinition


# Every environment variable app/config.py reads at import
KNOBS = ('RATE_KNF_LTC', 'BTC_FEE_RATE_SATVB', 'APP_DEBUG', 'LOG_LEVEL', 'CONFIG_DIR')

# The repository's own _CONFIG folder, two levels above app/
REPO_CONFIG_DIR = os.path.abspath(os.path.join(os.path.dirname(config.__file__), '..', '..', '_CONFIG'))


# A registry holding a chain under each of the given keys
def chains_named(*keys):
    return {key: ChainDefinition(
        short_name='KNF', full_name='KNF Coin', network='mainnet', bech32_hrp='knf',
        electrum_server='158.129.172.247:49002', block_explorer='/explorer', confirm_target=2,
    ) for key in keys}








############################################################
# TestKnobs
############################################################
#
# Every knob read from the environment at import, falling
# back to the classroom defaults — the module re-imported
# under a controlled environment and put back afterwards.
############################################################

class TestKnobs(unittest.TestCase):

    def reload_with(self, mounted=False, **values):
        # The module as a fresh process would read it from this environment
        # — with a /config folder mounted or not; the real environment's
        # reading is restored after the test
        self.addCleanup(importlib.reload, config)
        environment = {key: value for key, value in os.environ.items() if key not in KNOBS}
        environment.update(values)
        real_isdir = os.path.isdir
        isdir = lambda path: mounted if path == '/config' else real_isdir(path)
        with patch.dict(os.environ, environment, clear=True), patch('os.path.isdir', side_effect=isdir):
            importlib.reload(config)

    def test_unset_knobs_fall_back_to_the_classroom_defaults(self):
        self.reload_with()

        self.assertEqual(config.RATE_KNF_TO_LTC, 0.12345678)
        self.assertEqual(config.FEE_RATE_SATVB, 10)
        self.assertFalse(config.APP_DEBUG)
        self.assertEqual(config.LOG_LEVEL, 'INFO')
        self.assertEqual(config.CONFIG_DIR, REPO_CONFIG_DIR)

    def test_the_configuration_folder_mounted_at_config_is_the_one_read(self):
        self.reload_with(mounted=True)
        self.assertEqual(config.CONFIG_DIR, '/config')

    def test_every_knob_is_read_from_the_environment(self):
        self.reload_with(mounted=True, RATE_KNF_LTC='0.5', BTC_FEE_RATE_SATVB='3', APP_DEBUG='True',
                         LOG_LEVEL='debug', CONFIG_DIR='/srv/exchange-config')

        self.assertEqual(config.RATE_KNF_TO_LTC, 0.5)
        self.assertEqual(config.FEE_RATE_SATVB, 3)
        self.assertTrue(config.APP_DEBUG)
        self.assertEqual(config.LOG_LEVEL, 'DEBUG')
        self.assertEqual(config.CONFIG_DIR, '/srv/exchange-config')

    def test_debug_mode_needs_the_word_true(self):
        for value, expected in (('true', True), ('TRUE', True), ('1', False), ('yes', False)):
            with self.subTest(value=value):
                self.reload_with(APP_DEBUG=value)
                self.assertEqual(config.APP_DEBUG, expected)








############################################################
# TestValidate
############################################################
#
# The startup gate: a complete configuration passes, and each
# wrong setting stops the start with the sentence naming its
# knob.
############################################################

class TestValidate(unittest.TestCase):

    def setUp(self):
        seed = patch.dict(os.environ, {'EXCHANGE_PRIVATE_KEY': 'ab' * 32})
        seed.start()
        self.addCleanup(seed.stop)

    def refusal(self):
        with self.assertRaises(SystemExit) as caught:
            config.validate()
        return str(caught.exception)

    def test_a_complete_configuration_passes(self):
        self.assertIsNone(config.validate())

    def test_a_0x_prefix_on_the_seed_is_accepted(self):
        os.environ['EXCHANGE_PRIVATE_KEY'] = '0x' + 'ab' * 32
        self.assertIsNone(config.validate())

    def test_a_missing_seed_stops_the_start(self):
        del os.environ['EXCHANGE_PRIVATE_KEY']
        self.assertEqual(self.refusal(), '[CONFIG] EXCHANGE_PRIVATE_KEY environment variable is required (HD wallet seed)')

    def test_a_seed_that_is_not_hex_stops_the_start(self):
        os.environ['EXCHANGE_PRIVATE_KEY'] = 'correct horse battery staple'
        self.assertEqual(self.refusal(), '[CONFIG] EXCHANGE_PRIVATE_KEY must be a hex string')

    def test_a_seed_too_short_to_be_secret_stops_the_start(self):
        # Padded with zeros, a few hex digits would make a wallet anyone
        # could rebuild
        for seed in ('00', 'ab' * 15 + 'a', '0x' + 'ab' * 15):
            with self.subTest(seed=seed):
                os.environ['EXCHANGE_PRIVATE_KEY'] = seed
                self.assertEqual(self.refusal(), '[CONFIG] EXCHANGE_PRIVATE_KEY must be at least 32 hex characters (128 bits)')

    def test_a_seed_of_128_bits_is_enough(self):
        os.environ['EXCHANGE_PRIVATE_KEY'] = 'ab' * 16
        self.assertIsNone(config.validate())

    def test_a_rate_that_is_not_positive_stops_the_start(self):
        for rate in (0, -0.1):
            with self.subTest(rate=rate), patch.object(config, 'RATE_KNF_TO_LTC', rate):
                self.assertEqual(self.refusal(), f'[CONFIG] RATE_KNF_LTC must be positive, got {rate}')

    def test_a_fee_rate_that_is_not_positive_stops_the_start(self):
        with patch.object(config, 'FEE_RATE_SATVB', 0):
            self.assertEqual(self.refusal(), '[CONFIG] BTC_FEE_RATE_SATVB must be positive, got 0')

    def test_a_coins_file_configuring_other_chains_than_the_traded_ones_stops_the_start(self):
        for keys in (('knf',), ('knf', 'ltc4', 'btc4'), ('knf', 'ltc')):
            with self.subTest(keys=keys), patch('app.chains.CHAINS', chains_named(*keys)):
                self.assertEqual(self.refusal(), "[CONFIG] coins.py must configure exactly the chains the exchange "
                                                 f"trades, ['knf', 'ltc4'] — it configures {sorted(keys)}")

    def test_the_traded_chains_in_any_order_pass(self):
        with patch('app.chains.CHAINS', chains_named('ltc4', 'knf')):
            self.assertIsNone(config.validate())