############################################################
#  [*] Wallet tests — key math and chain-query hygiene
#
#  These use the REAL ExchangeWallet (bech32 + bitcoinlib key
#  derivation) with its Electrum client's requests stubbed
#  out, so they cover exactly the layer the fakes elsewhere
#  skip (the client itself is tested in
#  test_electrum_client.py):
#
#    - deterministic address derivation from the seed, and the
#      seed itself: a 0x prefix ignored, taken as 32 bytes
#    - address validation / scripthash construction, checked
#      against an independent computation
#    - UTXO de-duplication (the double-payout bug of 2026-07-15)
#    - tolerating a syncing server (tip height None -> 0)
#    - following a payout through its destination's history:
#      how deep it lies, in the mempool, or not there at all
#    - each wallet's own Electrum client, on its chain's
#      endpoint
#    - real payout and sweep transactions, signed and parsed
#      back: who is paid, the change, the fee estimate, dust,
#      which reserve coins pay — confirmed ones first, as many
#      as the amount and the fee together need — and a reserve
#      that cannot pay told apart from an outage
#    - what the reserve can spend, a syncing server refused
#    - refunds: who sent a deposit (the script its first input
#      spent — a server that does not hand a transaction out
#      raises, never reads as "no sender"), how coins are
#      shared out among their senders,
#      the refund transaction signed and parsed back, and each
#      script named as the address a student reads — bech32,
#      bech32m for taproot, none for a legacy one
############################################################


import hashlib
import os
import unittest
from unittest.mock import patch

import bech32
from bitcoinlib.transactions import Transaction

from app.chains import ChainDefinition
from app.electrum_client import ElectrumClient
from app.wallet import ExchangeWallet, COIN, ReserveShortfall, _bech32m_address, refund_plan


# The two chains the real wallet is built on, their Electrum
# endpoints never contacted
TEST_CHAIN = ChainDefinition(
    short_name='KNF',
    full_name='KNF Coin',
    network='mainnet',
    bech32_hrp='knf',
    electrum_server='127.0.0.1:1',   # transport is always patched out
    block_explorer='/explorer',
    confirm_target=2,
)


LTC_CHAIN = ChainDefinition(
    short_name='tLTC4',
    full_name='Litecoin Testnet4',
    network='testnet',
    bech32_hrp='tltc',
    electrum_server='127.0.0.1:1',
    block_explorer='/explorer',
    confirm_target=2,
)


# A real wallet on a throwaway seed; nothing reaches Electrum until a
# test stubs its client's requests
def make_wallet(chain=TEST_CHAIN):
    os.environ['EXCHANGE_PRIVATE_KEY'] = 'ab' * 32
    return ExchangeWallet(chain)


def utxo(txid_byte, value, height=50, tx_pos=0):
    # A reserve or deposit coin as listunspent reports it
    return {'tx_hash': txid_byte * 32, 'tx_pos': tx_pos, 'height': height, 'value': value}


# What a server whose node keeps no transaction index answers when asked for
# a confirmed transaction (the same while the index is still being built)
NOT_INDEXED = ("Electrum error: {'code': 2, 'message': \"daemon error: DaemonError({'code': -5, 'message': "
               "'No such mempool transaction. Use -txindex or provide a block hash to enable blockchain "
               "transaction queries. Use gettransaction for wallet transactions.'})\"}")


# Output scripts a deposit can come from: a SegWit key hash, a taproot
# key and a legacy key hash
P2WPKH = b'\x00\x14' + bytes(range(20))
P2TR = b'\x51\x20' + bytes(range(32))
P2PKH = bytes.fromhex('76a914' + '22' * 20 + '88ac')


def coin(txid_byte, value, refund_to, tx_pos=0):
    # A deposit coin and the script it goes back to
    return dict(utxo(txid_byte, value, tx_pos=tx_pos), refund_to=refund_to)








############################################################
# TestDerivation
############################################################
#
# Deterministic HD derivation: the reserve at index 0, every
# address carrying the chain's own prefix and valid on that
# chain alone.
############################################################

class TestDerivation(unittest.TestCase):

    def test_each_wallet_talks_to_its_chains_server_through_a_client_of_its_own(self):
        knf, ltc = make_wallet(TEST_CHAIN), make_wallet(LTC_CHAIN)

        self.assertIsInstance(knf.electrum, ElectrumClient)
        self.assertEqual((knf.electrum.host, knf.electrum.port), ('127.0.0.1', 1))
        self.assertIsNot(knf.electrum, ltc.electrum)

    def test_derivation_is_deterministic(self):
        a, b = make_wallet(), make_wallet()
        self.assertEqual(a.derive(5).address, b.derive(5).address)
        self.assertNotEqual(a.derive(5).address, a.derive(6).address)

    def test_reserve_is_index_zero(self):
        wallet = make_wallet()
        self.assertEqual(wallet.reserve.address, wallet.derive(0).address)

    def test_addresses_use_the_configured_prefix(self):
        wallet = make_wallet()
        self.assertTrue(wallet.derive(1).address.startswith('knf1q'))

    def test_own_addresses_validate_and_foreign_ones_do_not(self):
        wallet = make_wallet()
        self.assertTrue(wallet.is_valid_address(wallet.derive(1).address))
        self.assertFalse(wallet.is_valid_address('tltc1qgxlmvjc0a2s9htv6eqnm90secm3xmt9fyr2nrr'))
        self.assertFalse(wallet.is_valid_address('not-an-address'))
        self.assertFalse(wallet.is_valid_address(''))








############################################################
# TestChainQueries
############################################################
#
# UTXO de-duplication, and a syncing server's tip read as 0.
############################################################

class TestChainQueries(unittest.TestCase):

    def test_get_unspent_deduplicates_mempool_and_confirmed_views(self):
        # The exact double-payout scenario: the same outpoint reported once
        # from the mempool (height 0) and once from a fresh block.
        wallet = make_wallet()
        duplicated = [
            {'tx_hash': 'aa' * 32, 'tx_pos': 0, 'height': 0,    'value': 20 * COIN},
            {'tx_hash': 'aa' * 32, 'tx_pos': 0, 'height': 2202, 'value': 20 * COIN},
        ]

        with patch.object(wallet.electrum, 'request', return_value=duplicated):
            utxos = wallet.get_unspent('scripthash')
            received = wallet.get_received_sat('scripthash')

        self.assertEqual(len(utxos), 1)
        self.assertEqual(utxos[0]['height'], 2202)   # confirmed view wins
        self.assertEqual(received, 20 * COIN)        # NOT 40

    def test_distinct_utxos_are_all_kept(self):
        wallet = make_wallet()
        distinct = [
            {'tx_hash': 'aa' * 32, 'tx_pos': 0, 'height': 10, 'value': 5 * COIN},
            {'tx_hash': 'aa' * 32, 'tx_pos': 1, 'height': 10, 'value': 3 * COIN},
            {'tx_hash': 'bb' * 32, 'tx_pos': 0, 'height': 0,  'value': 2 * COIN},
        ]

        with patch.object(wallet.electrum, 'request', return_value=distinct):
            self.assertEqual(wallet.get_received_sat('scripthash'), 10 * COIN)

    def test_syncing_server_reports_tip_height_zero(self):
        wallet = make_wallet()
        with patch.object(wallet.electrum, 'request', return_value=None):
            self.assertEqual(wallet.get_tip_height(), 0)








############################################################
# TestSeed
############################################################
#
# How the seed is read: a 0x prefix ignored, exactly 32
# bytes taken, no seed no wallet.
############################################################

class TestSeed(unittest.TestCase):

    def seed(self, raw):
        with patch.dict(os.environ, {'EXCHANGE_PRIVATE_KEY': raw}):
            return ExchangeWallet._seed_bytes()

    def test_a_0x_prefix_is_ignored(self):
        self.assertEqual(self.seed('0x' + 'ab' * 32), bytes.fromhex('ab' * 32))

    def test_the_seed_is_taken_as_exactly_32_bytes(self):
        # Longer seeds are cut, shorter ones padded with zeros
        self.assertEqual(self.seed('ab' * 40), bytes.fromhex('ab' * 32))
        self.assertEqual(self.seed('abcd'), bytes.fromhex('abcd' + '00' * 30))

    def test_no_seed_no_wallet(self):
        with patch.dict(os.environ):
            os.environ.pop('EXCHANGE_PRIVATE_KEY', None)
            with self.assertRaises(ValueError) as caught:
                ExchangeWallet(TEST_CHAIN)

        self.assertEqual(str(caught.exception), 'EXCHANGE_PRIVATE_KEY environment variable not set')








############################################################
# TestAddresses
############################################################
#
# The address math, checked against an independent
# computation: the public key an address commits to,
# Electrum's scripthash, which addresses are valid.
############################################################

class TestAddresses(unittest.TestCase):

    def test_the_address_commits_to_the_derived_public_key(self):
        key = make_wallet().derive(3)
        _witver, program = bech32.decode('knf', key.address)
        expected = hashlib.new('ripemd160', hashlib.sha256(key.key.public_byte).digest()).digest()
        self.assertEqual(bytes(program), expected)

    def test_the_scripthash_is_electrums_for_the_address(self):
        # sha256 of the p2wpkh output script, byte-reversed
        key = make_wallet().derive(3)
        _witver, program = bech32.decode('knf', key.address)
        script = b'\x00\x14' + bytes(program)
        self.assertEqual(key.scripthash, hashlib.sha256(script).digest()[::-1].hex())

    def test_only_p2wpkh_addresses_of_this_chain_are_valid(self):
        wallet = make_wallet()
        program = list(range(20))
        good = bech32.encode('knf', 0, program)
        broken = good[:-1] + ('q' if good[-1] != 'q' else 'p')
        self.assertTrue(wallet.is_valid_address(good))

        for label, address in [
            ('another chain', bech32.encode('tltc', 0, program)),
            ('a script hash (P2WSH)', bech32.encode('knf', 0, list(range(32)))),
            ('witness version 1', bech32.encode('knf', 1, list(range(32)))),
            ('a broken checksum', broken),
        ]:
            with self.subTest(label):
                self.assertFalse(wallet.is_valid_address(address))

    def test_an_invalid_address_never_becomes_an_output_script(self):
        with self.assertRaises(ValueError) as caught:
            make_wallet()._address_to_script('knf1qbad')
        self.assertEqual(str(caught.exception), 'Invalid knf address: knf1qbad')

    def test_a_script_is_named_as_the_address_a_student_reads(self):
        wallet = make_wallet()
        key = wallet.derive(3)
        p2wsh = b'\x00\x20' + bytes(range(32))

        self.assertEqual(wallet.address_of(wallet._address_to_script(key.address)), key.address)
        self.assertEqual(wallet.address_of(p2wsh), bech32.encode('knf', 0, list(range(32))))
        self.assertEqual(wallet.address_of(P2TR), _bech32m_address('knf', 1, bytes(range(32))))
        self.assertIsNone(wallet.address_of(P2PKH))

    def test_a_taproot_address_carries_the_bech32m_checksum(self):
        # BIP-350's vector: the taproot output of the generator point
        program = bytes.fromhex('79be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798')
        self.assertEqual(_bech32m_address('bc', 1, program), 'bc1p0xlxvlhemja6c4dqv22uapctqupfhlxm9h8z3k2e72q4k9hcz7vqzk5jj0')








############################################################
# TestChainAnswers
############################################################
#
# How each chain query reads the server's answers — and an
# outage that must not read as an answer.
############################################################

class TestChainAnswers(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet()

    def answer(self, value=None, error=None):
        if error:
            return patch.object(self.wallet.electrum, 'request', side_effect=error)
        return patch.object(self.wallet.electrum, 'request', return_value=value)

    def test_balances_are_read_as_whole_satoshis(self):
        with self.answer({'confirmed': 482150000000, 'unconfirmed': -50000000}):
            self.assertEqual(self.wallet.get_balance_sat('scripthash'), {'confirmed': 482150000000, 'unconfirmed': -50000000})
        with self.answer(None):
            self.assertEqual(self.wallet.get_balance_sat('scripthash'), {'confirmed': 0, 'unconfirmed': 0})

    def test_an_address_never_used_has_no_history_and_no_coins(self):
        with self.answer(None):
            self.assertEqual(self.wallet.get_history('scripthash'), [])
            self.assertEqual(self.wallet.get_unspent('scripthash'), [])
            self.assertEqual(self.wallet.get_received_sat('scripthash'), 0)

    def test_coins_still_in_the_mempool_count_as_received(self):
        # A deposit is seen the moment it is broadcast; the worker's rate
        # lock then waits for its confirmations
        with self.answer([utxo('aa', 7 * COIN, height=0)]):
            self.assertEqual(self.wallet.get_received_sat('scripthash'), 7 * COIN)

    def test_a_transaction_is_its_raw_hex(self):
        with self.answer('0200000001'):
            self.assertEqual(self.wallet.get_transaction('ab' * 32), '0200000001')

    def test_a_transaction_the_server_does_not_hand_out_raises_in_its_own_words(self):
        # Only transactions the chain holds are asked about, so a refusal (a
        # node without a transaction index) is trouble like an outage - read
        # as "missing", it would leave a refund without its sender
        for error in (RuntimeError(NOT_INDEXED), ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')):
            with self.subTest(error=type(error).__name__):
                with self.answer(error=error):
                    with self.assertRaises(type(error)) as raised:
                        self.wallet.get_transaction('ab' * 32)
                self.assertEqual(str(raised.exception), str(error))

    def test_a_broadcast_hands_the_raw_transaction_to_the_server(self):
        with self.answer('cd' * 32) as rpc:
            self.assertEqual(self.wallet.broadcast('0200beef'), 'cd' * 32)
        rpc.assert_called_once_with('blockchain.transaction.broadcast', ['0200beef'])








############################################################
# TestFollowingAPayout
############################################################
#
# A payout followed through its destination's history: how
# deep it lies, in the mempool, or not there at all.
############################################################

class TestFollowingAPayout(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet()
        self.student = self.wallet.derive(5).address

    def chain(self, history, tip=105):
        # The two questions payout_confirmations asks: the destination's
        # history and the tip of the chain
        answers = {'blockchain.scripthash.get_history': history,
                   'blockchain.headers.subscribe': {'height': tip}}
        return patch.object(self.wallet.electrum, 'request', side_effect=lambda method, _params: answers[method])

    def test_a_payout_is_as_deep_as_its_block_lies_under_the_tip(self):
        with self.chain([{'tx_hash': 'aa' * 32, 'height': 104}], tip=105) as rpc:
            self.assertEqual(self.wallet.payout_confirmations('aa' * 32, self.student), 2)
        rpc.assert_any_call('blockchain.scripthash.get_history', [self.wallet._address_to_scripthash(self.student)])

    def test_a_server_lagging_behind_the_payout_block_counts_none(self):
        with self.chain([{'tx_hash': 'aa' * 32, 'height': 104}], tip=102):
            self.assertEqual(self.wallet.payout_confirmations('aa' * 32, self.student), 0)

    def test_a_payout_in_the_mempool_is_there_with_no_confirmations(self):
        # Electrum puts a mempool transaction at 0, or -1 while its inputs
        # are unconfirmed too
        for height in (0, -1):
            with self.subTest(height=height), self.chain([{'tx_hash': 'aa' * 32, 'height': height}]):
                self.assertEqual(self.wallet.payout_confirmations('aa' * 32, self.student), 0)

    def test_a_refund_is_followed_through_the_history_of_the_address_it_spends(self):
        with self.chain([{'tx_hash': 'aa' * 32, 'height': 104}], tip=105) as rpc:
            self.assertEqual(self.wallet.confirmations('aa' * 32, 'deposit-scripthash'), 2)
        rpc.assert_any_call('blockchain.scripthash.get_history', ['deposit-scripthash'])

    def test_a_payout_the_destination_history_does_not_hold_is_none(self):
        with self.chain([{'tx_hash': 'bb' * 32, 'height': 104}]):
            self.assertIsNone(self.wallet.payout_confirmations('aa' * 32, self.student))
        with self.chain(None):
            self.assertIsNone(self.wallet.payout_confirmations('aa' * 32, self.student))

    def test_an_outage_is_not_mistaken_for_a_lost_payout(self):
        # Reading an outage as "not there" would only rebroadcast the same
        # transaction - but the outage surfaces instead
        with patch.object(self.wallet.electrum, 'request', side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')):
            with self.assertRaises(ConnectionError):
                self.wallet.payout_confirmations('aa' * 32, self.student)








############################################################
# TestPayoutTransaction
############################################################
#
# Real payout transactions, signed and parsed back: who is
# paid, the change, the fee, and which reserve coins pay.
############################################################

class TestPayoutTransaction(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet(LTC_CHAIN)
        self.student = bech32.encode('tltc', 0, list(range(20)))

    def build(self, utxos, amount_sat):
        with patch.object(self.wallet.electrum, 'request', return_value=utxos):
            return self.wallet.build_payout_tx(self.student, amount_sat, 10)

    def script(self, address):
        return self.wallet._address_to_script(address)

    def spent(self, raw):
        return [entry.prev_txid.hex() for entry in Transaction.parse_hex(raw, network='litecoin_testnet').inputs]

    def outputs(self, raw):
        return [(out.value, out.lock_script) for out in Transaction.parse_hex(raw, network='litecoin_testnet').outputs]

    def test_pays_the_student_and_returns_the_change_to_the_reserve(self):
        txid, raw = self.build([utxo('aa', 3 * COIN)], 2 * COIN)

        self.assertEqual(Transaction.parse_hex(raw, network='litecoin_testnet').txid, txid)
        self.assertEqual(self.outputs(raw), [
            (2 * COIN, self.script(self.student)),
            (3 * COIN - 2 * COIN - 1410, self.script(self.wallet.reserve.address)),
        ])

    def test_the_fee_follows_the_size_estimate_and_the_fee_rate(self):
        # 68 vbytes per input, 31 per output, 11 fixed — at 10 sat/vbyte
        _txid, raw = self.build([utxo('aa', 1 * COIN), utxo('bb', 1 * COIN)], int(1.5 * COIN))

        self.assertEqual(len(self.spent(raw)), 2)
        fee = 2 * COIN - sum(value for value, _script in self.outputs(raw))
        self.assertEqual(fee, (2 * 68 + 2 * 31 + 11) * 10)

    def test_takes_no_more_reserve_coins_than_the_payout_needs(self):
        _txid, raw = self.build([utxo('aa', 2 * COIN), utxo('bb', 2 * COIN)], 1 * COIN)
        self.assertEqual(self.spent(raw), ['aa' * 32])

    def test_change_too_small_to_spend_is_left_to_the_fee(self):
        _txid, raw = self.build([utxo('aa', 2 * COIN + 1410 + 500)], 2 * COIN)
        self.assertEqual(self.outputs(raw), [(2 * COIN, self.script(self.student))])

    def test_an_empty_reserve_cannot_pay(self):
        # An answer the worker acts on, told apart from an outage by its type
        with self.assertRaises(ReserveShortfall) as caught:
            self.build([], 1 * COIN)
        self.assertEqual(str(caught.exception), 'Reserve address has no funds to pay out')

    def test_a_reserve_short_of_the_amount_and_the_fee_cannot_pay(self):
        with self.assertRaises(ReserveShortfall) as caught:
            self.build([utxo('aa', 2 * COIN)], 2 * COIN)
        self.assertEqual(str(caught.exception), 'Insufficient reserve funds: have 2 tLTC4, need 2.0000141 tLTC4')

    def test_an_outage_is_not_mistaken_for_an_empty_reserve(self):
        with patch.object(self.wallet.electrum, 'request', side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')):
            with self.assertRaises(ConnectionError):
                self.wallet.build_payout_tx(self.student, 1 * COIN, 10)

    def test_a_destination_on_another_chain_is_refused_before_anything_is_read(self):
        knf_address = bech32.encode('knf', 0, list(range(20)))

        with patch.object(self.wallet.electrum, 'request') as rpc:
            with self.assertRaises(ValueError) as caught:
                self.wallet.build_payout_tx(knf_address, 1 * COIN)

        rpc.assert_not_called()
        self.assertEqual(str(caught.exception), f'Invalid tltc address: {knf_address}')

    def test_enough_coins_are_gathered_to_cover_the_fee_too(self):
        # One coin covers the amount but not its fee as well
        _txid, raw = self.build([utxo('aa', 1 * COIN), utxo('bb', 1 * COIN)], 1 * COIN)
        self.assertEqual(len(self.spent(raw)), 2)

    def test_confirmed_reserve_coins_are_spent_before_unconfirmed_ones(self):
        # A sweep or top-up still in the mempool could vanish in a
        # reorganisation and take the payout with it
        _txid, raw = self.build([utxo('bb', 5 * COIN, height=0), utxo('aa', 3 * COIN, height=50)], 2 * COIN)
        self.assertEqual(self.spent(raw), ['aa' * 32])

    def test_unconfirmed_coins_still_pay_when_the_confirmed_ones_fall_short(self):
        _txid, raw = self.build([utxo('bb', 5 * COIN, height=0), utxo('aa', 1 * COIN, height=50)], 2 * COIN)
        self.assertEqual(self.spent(raw), ['aa' * 32, 'bb' * 32])








############################################################
# TestSweepTransaction
############################################################
#
# Real sweep transactions: everything on a deposit address
# to the reserve, nothing when nothing is worth sweeping.
############################################################

class TestSweepTransaction(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet(LTC_CHAIN)
        self.deposit = self.wallet.derive(12)

    def sweep(self, utxos):
        with patch.object(self.wallet.electrum, 'request', return_value=utxos):
            return self.wallet.build_sweep_tx(self.deposit, 10)

    def test_everything_on_the_deposit_address_goes_to_the_reserve(self):
        txid, raw, amount = self.sweep([utxo('aa', 2 * COIN), utxo('bb', 3 * COIN, tx_pos=1)])
        parsed = Transaction.parse_hex(raw, network='litecoin_testnet')

        self.assertEqual(parsed.txid, txid)
        self.assertEqual(len(parsed.inputs), 2)
        self.assertEqual(amount, 5 * COIN - (2 * 68 + 31 + 11) * 10)
        self.assertEqual([(out.value, out.lock_script) for out in parsed.outputs],
                         [(amount, self.wallet._address_to_script(self.wallet.reserve.address))])

    def test_an_empty_address_has_nothing_to_sweep(self):
        self.assertIsNone(self.sweep([]))

    def test_coins_worth_no_more_than_dust_after_the_fee_stay_where_they_are(self):
        # One input costs a 1100 sat fee; 546 sat is the dust limit
        self.assertIsNone(self.sweep([utxo('aa', 1100 + 546)]))
        self.assertIsNotNone(self.sweep([utxo('aa', 1100 + 547)]))

    def test_given_coins_only_those_are_swept_and_the_address_is_not_read(self):
        # The coins an order's payout paid for; a later one stays to go back
        paid = [utxo('aa', 2 * COIN)]
        with patch.object(self.wallet.electrum, 'request') as rpc:
            txid, raw, amount = self.wallet.build_sweep_tx(self.deposit, 10, paid)

        rpc.assert_not_called()
        parsed = Transaction.parse_hex(raw, network='litecoin_testnet')
        self.assertEqual([entry.prev_txid.hex() for entry in parsed.inputs], ['aa' * 32])
        self.assertEqual(amount, 2 * COIN - 1100)








############################################################
# TestReserveBalance
############################################################
#
# What the reserve can spend, as a new order is checked
# against it: confirmed and unconfirmed together, never read
# from a server without a chain tip.
############################################################

class TestReserveBalance(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet()

    def chain(self, tip, balance):
        answers = {'blockchain.headers.subscribe': {'height': tip} if tip else None,
                   'blockchain.scripthash.get_balance': balance}
        return patch.object(self.wallet.electrum, 'request', side_effect=lambda method, _params: answers[method])

    def test_confirmed_and_unconfirmed_coins_both_count(self):
        # A sweep still in the mempool pays a payout once confirmed coins fall
        # short; a payout of its own in the mempool already counts against it
        with self.chain(105, {'confirmed': 3 * COIN, 'unconfirmed': -1 * COIN}) as rpc:
            self.assertEqual(self.wallet.reserve_balance_sat(), 2 * COIN)
        rpc.assert_any_call('blockchain.scripthash.get_balance', [self.wallet.reserve.scripthash])

    def test_a_syncing_server_is_not_asked_for_the_balance(self):
        # It would answer 0 for every address — an empty reserve that is not
        with self.chain(0, {'confirmed': 0, 'unconfirmed': 0}):
            with self.assertRaises(RuntimeError) as caught:
                self.wallet.reserve_balance_sat()
        self.assertEqual(str(caught.exception), 'Electrum server is still syncing (no chain tip yet)')

    def test_an_outage_raises(self):
        with patch.object(self.wallet.electrum, 'request', side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')):
            with self.assertRaises(ConnectionError):
                self.wallet.reserve_balance_sat()








############################################################
# TestSenders
############################################################
#
# Who sent a deposit: the output script its transaction's
# first input spent, found through two real transactions —
# none for a coinbase or a transaction that cannot be read,
# and a raise, never none, while the server does not hand
# one of the two out.
############################################################

class TestSenders(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet(LTC_CHAIN)
        self.deposit = self.wallet.derive(12)
        self.student = bech32.encode('tltc', 0, list(range(20)))

        # A transaction paying the student (output 0, its change to the
        # reserve at output 1), and a deposit whose input is then pointed at
        # the student's coin — the signature no longer matters, only the
        # outpoint it names
        with patch.object(self.wallet.electrum, 'request', return_value=[utxo('ee', 5 * COIN)]):
            self.funding_txid, self.funding_raw = self.wallet.build_payout_tx(self.student, 3 * COIN, 10)
        with patch.object(self.wallet.electrum, 'request', return_value=[utxo('ab', 3 * COIN)]):
            _txid, deposit_raw = self.wallet.build_payout_tx(self.deposit.address, 1 * COIN, 10)
        self.deposit_raw = deposit_raw.replace('ab' * 32, bytes.fromhex(self.funding_txid)[::-1].hex())
        self.deposit_txid = Transaction.parse_hex(self.deposit_raw, network='litecoin_testnet').txid

    def knows(self, transactions):
        # The server's answers to blockchain.transaction.get: raw hex, or the
        # refusal of a node whose transaction index does not hold it
        def answer(_method, params):
            if params[0] not in transactions:
                raise RuntimeError(NOT_INDEXED)
            return transactions[params[0]]
        return patch.object(self.wallet.electrum, 'request', side_effect=answer)

    def test_the_sender_is_the_script_the_first_input_spent(self):
        with self.knows({self.deposit_txid: self.deposit_raw, self.funding_txid: self.funding_raw}):
            self.assertEqual(self.wallet.sender_of(self.deposit_txid), self.wallet._address_to_script(self.student))

    def test_a_transaction_the_server_does_not_hand_out_raises_rather_than_reading_as_no_sender(self):
        # The sender is there, only not found yet: the worker asks again
        for missing, known in (('the deposit', {self.funding_txid: self.funding_raw}),
                               ('the transaction it spends', {self.deposit_txid: self.deposit_raw})):
            with self.subTest(missing=missing):
                with self.knows(known):
                    with self.assertRaises(RuntimeError):
                        self.wallet.sender_of(self.deposit_txid)

    def test_a_coinbase_has_no_sender(self):
        coinbase = ('01000000' '01' + '00' * 32 + 'ffffffff' + '03' + '510101' + 'ffffffff' + '01' +
                    (50 * COIN).to_bytes(8, 'little').hex() + '16' + '0014' + '11' * 20 + '00000000')
        with self.knows({'cb' * 32: coinbase}):
            self.assertIsNone(self.wallet.sender_of('cb' * 32))

    def test_a_transaction_that_cannot_be_read_has_no_sender(self):
        with self.knows({self.deposit_txid: 'not a transaction'}):
            self.assertIsNone(self.wallet.sender_of(self.deposit_txid))

    def test_an_outage_is_not_mistaken_for_an_unknown_sender(self):
        with patch.object(self.wallet.electrum, 'request', side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out')):
            with self.assertRaises(ConnectionError):
                self.wallet.sender_of(self.deposit_txid)








############################################################
# TestRefundPlan
############################################################
#
# How coins are shared out among their senders: one output
# each, each paying the fee of its own coins and output, the
# first the fixed part too, a sender left with dust dropped.
############################################################

class TestRefundPlan(unittest.TestCase):

    def test_one_senders_coins_go_back_together_less_one_fee(self):
        # 68 vbytes an input, 31 the output, 11 fixed — at 10 sat/vbyte
        plan = refund_plan([coin('aa', 2 * COIN, P2WPKH), coin('bb', 1 * COIN, P2WPKH)], 10)
        self.assertEqual([(to, amount, len(group)) for to, amount, group in plan],
                         [(P2WPKH, 3 * COIN - (2 * 68 + 31 + 11) * 10, 2)])

    def test_each_sender_pays_for_its_own_coins_and_the_first_for_the_rest(self):
        plan = refund_plan([coin('aa', 2 * COIN, P2WPKH), coin('bb', 1 * COIN, P2TR)], 10)
        self.assertEqual([(to, amount) for to, amount, _group in plan], [
            (P2WPKH, 2 * COIN - (68 + 31 + 11) * 10),
            (P2TR, 1 * COIN - (68 + 31) * 10),
        ])

    def test_a_sender_left_with_dust_is_dropped_and_the_rest_share_again(self):
        # 1500 sat cannot pay its 990 sat share and stay above dust; the other
        # sender then pays the fixed part too
        plan = refund_plan([coin('aa', 1500, P2TR), coin('bb', 1 * COIN, P2WPKH)], 10)
        self.assertEqual([(to, amount) for to, amount, _group in plan], [(P2WPKH, 1 * COIN - (68 + 31 + 11) * 10)])

    def test_nothing_worth_sending_back_is_no_plan(self):
        self.assertEqual(refund_plan([coin('aa', 1100 + 546, P2WPKH)], 10), [])
        self.assertEqual(refund_plan([], 10), [])








############################################################
# TestRefundTransaction
############################################################
#
# Real refunds, signed and parsed back: the coins in, one
# output per sender out, whatever kind of script it is.
############################################################

class TestRefundTransaction(unittest.TestCase):

    def setUp(self):
        self.wallet = make_wallet(TEST_CHAIN)
        self.deposit = self.wallet.derive(7)

    def test_every_sender_gets_its_coins_back_in_its_own_script(self):
        coins = [coin('aa', 3 * COIN, P2WPKH), coin('bb', 1 * COIN, P2TR, tx_pos=1),
                 coin('cc', 2 * COIN, P2PKH, tx_pos=2), coin('dd', 1 * COIN, P2WPKH)]

        txid, raw, recipients, spent = self.wallet.build_refund_tx(self.deposit, coins, 10)

        parsed = Transaction.parse_hex(raw, network='litecoin')
        self.assertEqual(parsed.txid, txid)
        self.assertEqual(sorted(entry.prev_txid.hex()[:2] for entry in parsed.inputs), ['aa', 'bb', 'cc', 'dd'])
        self.assertEqual([(out.lock_script, out.value) for out in parsed.outputs], recipients)
        self.assertEqual(recipients, [
            (P2WPKH, 4 * COIN - (2 * 68 + 31 + 11) * 10),
            (P2TR, 1 * COIN - (68 + 31) * 10),
            (P2PKH, 2 * COIN - (68 + 31) * 10),
        ])
        self.assertEqual(len(spent), 4)

    def test_a_senders_dust_is_left_out_of_the_refund(self):
        txid, raw, recipients, spent = self.wallet.build_refund_tx(
            self.deposit, [coin('aa', 1500, P2TR), coin('bb', 1 * COIN, P2WPKH)], 10)

        self.assertEqual([entry['tx_hash'] for entry in spent], ['bb' * 32])
        self.assertEqual(len(Transaction.parse_hex(raw, network='litecoin').inputs), 1)

    def test_nothing_worth_sending_back_is_no_refund(self):
        self.assertIsNone(self.wallet.build_refund_tx(self.deposit, [coin('aa', 1500, P2WPKH)], 10))
