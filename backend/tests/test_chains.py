############################################################
#  [*] Chain registry tests — the operator's coins file
#
#  The coins file the repository ships, read where the app
#  reads it (CONFIG_DIR — runTests.sh mounts _CONFIG there):
#  it loads, configures exactly the chains the exchange
#  trades, and each chain takes the facts of its coin. Then
#  chain_definitions against crafted entries: every fault an
#  operator can make stops the boot with a sentence naming
#  the chain and the fault — a misspelled or missing key, a
#  section of the wrong shape, an unknown coin or flavour, a
#  confirmation target that is no whole number of at least
#  one, an Electrum endpoint that is not host:port or has no
#  real port, an explorer that is neither a URL nor a path, a
#  name left empty, a key a URL cannot carry. load_chains
#  turns every fault of the file itself — missing, not
#  runnable, without CHAIN_CONFIGS — into a "[CONFIG]"
#  sentence naming the file. Last, the coin registry: the
#  facts per coin and flavour, the known options named, the
#  real-money Litecoin absent.
############################################################


import copy
import os
import shutil
import tempfile
import unittest

from app import config
from app.chains import CHAINS, ChainDefinition, chain_definitions, load_chains
from app.coins import COINS, coin_params
from app.service import ASSET_TO_NETWORK


# The coins file the app reads
COINS_FILE = os.path.join(config.CONFIG_DIR, 'coins.py')

# A valid entry, as the shipped file writes the KNF chain
ENTRY = {
    'short_name': 'KNF',
    'full_name': 'KNF Coin',
    'exchange': {
        'coin': 'knfcoin',
        'network': 'mainnet',
        'confirm_target': 2,
        'electrum_server': '158.129.172.247:49002',
    },
    'explorer': {
        'block_explorer': '/explorer',
    },
}


# The valid entry with some of its parts replaced — None for a
# part removes it
def entry_with(**parts):
    entry = copy.deepcopy(ENTRY)
    for path, value in parts.items():
        section, _, key = path.rpartition('__')
        target = entry[section] if section else entry
        if value is None:
            target.pop(key)
        else:
            target[key] = value
    return entry








############################################################
# TestTheShippedFile
############################################################
#
# The repository's _CONFIG/coins.py, loaded the way the app
# loads it at boot.
############################################################

class TestTheShippedFile(unittest.TestCase):

    def test_it_loads_and_configures_exactly_the_traded_chains(self):
        chains = load_chains(COINS_FILE)

        self.assertEqual(sorted(chains), sorted(set(ASSET_TO_NETWORK.values())))
        self.assertEqual(chains, CHAINS)

    def test_each_chain_takes_the_facts_of_its_coin(self):
        self.assertEqual((CHAINS['knf'].network, CHAINS['knf'].bech32_hrp), ('mainnet', 'knf'))
        self.assertEqual((CHAINS['ltc4'].network, CHAINS['ltc4'].bech32_hrp), ('testnet', 'tltc'))

    def test_every_chain_has_names_an_endpoint_and_a_confirmation_target(self):
        for key, chain in CHAINS.items():
            with self.subTest(chain=key):
                self.assertTrue(chain.short_name and chain.full_name)
                self.assertRegex(chain.electrum_server, r'^[\w.\-]+:\d+$')
                self.assertGreaterEqual(chain.confirm_target, 1)








############################################################
# TestChainDefinitions
############################################################
#
# What a valid entry becomes, and the sentence each fault in
# an entry stops the boot with.
############################################################

class TestChainDefinitions(unittest.TestCase):

    def fault(self, entry, key='knf'):
        with self.assertRaises(ValueError) as caught:
            chain_definitions({key: entry})
        return str(caught.exception)

    def test_a_valid_entry_becomes_its_definition(self):
        self.assertEqual(chain_definitions({'knf': ENTRY}), {'knf': ChainDefinition(
            short_name='KNF', full_name='KNF Coin', network='mainnet', bech32_hrp='knf',
            electrum_server='158.129.172.247:49002', block_explorer='/explorer', confirm_target=2,
        )})

    def test_the_explorer_is_optional(self):
        chain = chain_definitions({'knf': entry_with(explorer=None)})['knf']
        self.assertIsNone(chain.block_explorer)

    def test_an_explorer_may_be_a_url_or_a_path_on_this_site(self):
        for url in ('https://litecoinspace.org/testnet', 'http://explorer.example', '/explorer'):
            with self.subTest(url=url):
                chain = chain_definitions({'knf': entry_with(explorer__block_explorer=url)})['knf']
                self.assertEqual(chain.block_explorer, url)

    def test_the_chains_keep_the_files_order(self):
        chains = chain_definitions({'ltc4': ENTRY, 'knf': ENTRY})
        self.assertEqual(list(chains), ['ltc4', 'knf'])

    def test_the_sentence_names_the_chain_and_the_fault(self):
        entry = entry_with(exchange__electrum='158.129.172.247:50002')
        self.assertEqual(self.fault(entry, key='ltc4'),
                         "chain 'ltc4' is misconfigured: unknown key 'electrum' in the 'exchange' section")

    def test_a_misspelled_key_stops_the_boot(self):
        for parts, where in (({'shortname': 'KNF'}, 'the entry'),
                             ({'exchange__confirmations': 2}, "the 'exchange' section"),
                             ({'explorer__url': '/explorer'}, "the 'explorer' section")):
            with self.subTest(where=where):
                name = next(iter(parts)).rpartition('__')[2]
                self.assertIn(f"unknown key '{name}' in {where}", self.fault(entry_with(**parts)))

    def test_a_missing_key_or_section_stops_the_boot(self):
        for part, sentence in (('full_name', "the entry lacks 'full_name'"),
                               ('exchange', "the entry lacks 'exchange'"),
                               ('exchange__electrum_server', "the 'exchange' section lacks 'electrum_server'"),
                               ('explorer__block_explorer', "the 'explorer' section lacks 'block_explorer'")):
            with self.subTest(part=part):
                self.assertIn(sentence, self.fault(entry_with(**{part: None})))

    def test_a_section_that_is_not_a_dict_stops_the_boot(self):
        for part in ('exchange', 'explorer'):
            with self.subTest(part=part):
                self.assertIn(f"the '{part}' section must be a dict", self.fault(entry_with(**{part: 'knfcoin'})))
        self.assertIn('the entry must be a dict', self.fault(['knfcoin']))

    def test_an_unknown_coin_names_the_known_ones(self):
        self.assertIn("unknown coin 'dogecoin' — known coins: ['knfcoin', 'litecoin']",
                      self.fault(entry_with(exchange__coin='dogecoin')))

    def test_an_unknown_flavour_names_the_available_ones(self):
        self.assertIn("coin 'knfcoin' has no 'testnet' flavour — available: ['mainnet']",
                      self.fault(entry_with(exchange__network='testnet')))

    def test_a_confirmation_target_that_is_no_whole_number_of_at_least_one_stops_the_boot(self):
        for target in (0, -1, 1.5, True, '2'):
            with self.subTest(target=target):
                self.assertIn(f'confirm_target must be a whole number of at least 1, got {target!r}',
                              self.fault(entry_with(exchange__confirm_target=target)))

    def test_an_electrum_endpoint_that_is_not_host_and_port_stops_the_boot(self):
        for endpoint in ('158.129.172.247', ':50002', '158.129.172.247:ssl', 'ssl://158.129.172.247:50002', 50002):
            with self.subTest(endpoint=endpoint):
                self.assertIn(f'electrum_server must be host:port, got {endpoint!r}',
                              self.fault(entry_with(exchange__electrum_server=endpoint)))

    def test_an_impossible_electrum_port_stops_the_boot(self):
        for port in ('0', '65536', '99999'):
            with self.subTest(port=port):
                self.assertIn(f'electrum_server port {port} is not a valid TCP port (1-65535)',
                              self.fault(entry_with(exchange__electrum_server=f'158.129.172.247:{port}')))

    def test_an_explorer_that_is_neither_a_url_nor_a_path_stops_the_boot(self):
        for url in ('explorer', 'ftp://explorer.example', '', 'https://', 7):
            with self.subTest(url=url):
                self.assertIn(f'block_explorer must be an http(s) URL or a path on this site, got {url!r}',
                              self.fault(entry_with(explorer__block_explorer=url)))

    def test_a_name_left_empty_stops_the_boot(self):
        for name in ('short_name', 'full_name'):
            for value in ('', '   ', 5):
                with self.subTest(name=name, value=value):
                    self.assertIn(f'{name} must be a non-empty text, got {value!r}',
                                  self.fault(entry_with(**{name: value})))

    def test_a_key_a_url_cannot_carry_stops_the_boot(self):
        for key in ('knf/main', 'k n f', 'knf.', '', 5):
            with self.subTest(key=key):
                with self.assertRaises(ValueError) as caught:
                    chain_definitions({key: ENTRY})
                self.assertEqual(str(caught.exception),
                                 f"chain key {key!r} is not URL-safe — use letters, digits, '-' and '_' only")

    def test_the_map_must_hold_chains(self):
        for configs in ({}, [ENTRY], None, 'knf'):
            with self.subTest(configs=configs):
                with self.assertRaises(ValueError) as caught:
                    chain_definitions(configs)
                self.assertIn('CHAIN_CONFIGS must be a non-empty dict of chains', str(caught.exception))








############################################################
# TestLoadingTheFile
############################################################
#
# load_chains against coins files in a scratch folder: the
# chains of a valid file, and a "[CONFIG]" sentence naming the
# file for every fault.
############################################################

class TestLoadingTheFile(unittest.TestCase):

    def setUp(self):
        self.folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.folder)
        self.path = os.path.join(self.folder, 'coins.py')

    def write(self, text):
        with open(self.path, 'w') as coins:
            coins.write(text)

    def refusal(self):
        with self.assertRaises(SystemExit) as caught:
            load_chains(self.path)
        return str(caught.exception)

    def test_a_valid_file_gives_its_chains(self):
        self.write(f'CHAIN_CONFIGS = {{"knf": {ENTRY!r}}}\n')
        self.assertEqual(list(load_chains(self.path)), ['knf'])

    def test_a_missing_file_names_the_path_and_the_mount_it_needs(self):
        self.assertEqual(self.refusal(), f'[CONFIG] no coins file at {self.path} — '
                                         'mount the _CONFIG folder at /config (./_CONFIG:/config:ro)')

    def test_a_file_python_cannot_run_names_the_file(self):
        self.write('CHAIN_CONFIGS = {\n')
        self.assertTrue(self.refusal().startswith(f'[CONFIG] {self.path} could not be loaded: '))

    def test_a_file_without_chain_configs_names_the_file(self):
        self.write('CHAINS = {}\n')
        self.assertEqual(self.refusal(), f'[CONFIG] {self.path} defines no CHAIN_CONFIGS')

    def test_a_misconfigured_chain_names_the_file_and_the_chain(self):
        broken = entry_with(exchange__coin='bitcoin')
        self.write(f'CHAIN_CONFIGS = {{"btc4": {broken!r}}}\n')
        self.assertEqual(self.refusal(), f"[CONFIG] {self.path}: chain 'btc4' is misconfigured: "
                                         "unknown coin 'bitcoin' — known coins: ['knfcoin', 'litecoin']")








############################################################
# TestCoinRegistry
############################################################
#
# The protocol facts app/coins.py holds for each coin and
# flavour, and the sentences of an unknown one.
############################################################

class TestCoinRegistry(unittest.TestCase):

    def test_each_coin_has_the_bech32_prefix_of_its_flavour(self):
        self.assertEqual(coin_params('knfcoin', 'mainnet'), {'bech32_hrp': 'knf'})
        self.assertEqual(coin_params('litecoin', 'testnet'), {'bech32_hrp': 'tltc'})

    def test_an_unknown_coin_names_the_known_ones(self):
        with self.assertRaises(ValueError) as caught:
            coin_params('bitcoin', 'testnet')
        self.assertEqual(str(caught.exception), "unknown coin 'bitcoin' — known coins: ['knfcoin', 'litecoin']")

    def test_an_unknown_flavour_names_the_available_ones(self):
        with self.assertRaises(ValueError) as caught:
            coin_params('litecoin', 'regtest')
        self.assertEqual(str(caught.exception), "coin 'litecoin' has no 'regtest' flavour — available: ['testnet']")

    def test_real_money_litecoin_is_not_in_the_registry(self):
        # No configuration can make the exchange pay out real litecoin
        with self.assertRaises(ValueError):
            coin_params('litecoin', 'mainnet')

    def test_the_facts_handed_out_leave_the_registry_as_it_is(self):
        coin_params('knfcoin', 'mainnet')['bech32_hrp'] = 'changed'
        self.assertEqual(COINS['knfcoin']['mainnet'], {'bech32_hrp': 'knf'})
