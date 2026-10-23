############################################################
#  [*] Service tests — validation, pricing and order creation
#
#  Everything the request-facing half of the exchange promises:
#  orders are validated before touching the chain, priced
#  server-side, and exchange-owned addresses are refused as
#  destinations — each refusal in the exact sentence the SPA
#  shows the student. An order is only taken while the reserve
#  that would pay it out can cover it: what that reserve holds
#  less what it owes the orders paid into, a reserve that
#  cannot be read taking no order at all. Around that: both
#  directions of the one pair, trimmed inputs, inclusive
#  limits, deposit indexes that never repeat (also under
#  concurrent requests), the 30-minute deadline, the order
#  records, the rates and reserves snapshots with what each
#  reserve can still pay out, the coin logos every answer
#  advertises (null for a coin without a logo file), and the
#  wallets built once per chain.
############################################################


import os
import threading
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.config import RATE_KNF_TO_LTC
from app.service import AMOUNT_LIMITS, ExchangeService, Unavailable, ValidationError, KNF, LTC
from app.wallet import COIN

from tests.base import ExchangeTestCase, TEST_CHAINS


# The refusal of an amount outside an asset's limits, as the service words
# it - from the limits configured, whatever they are
def outside_the_limits(asset):
    return f"Amount must be between {AMOUNT_LIMITS[asset]['min']} and {AMOUNT_LIMITS[asset]['max']} {asset}"








############################################################
# TestCreateOrder
############################################################
#
# create_order: the order it stores, every refusal a sentence
# the student can act on and leaving no trace, deposit
# addresses never shared — concurrent orders included — and
# the 30-minute deadline.
############################################################

class TestCreateOrder(ExchangeTestCase):

    def test_happy_path(self):
        order = self.create_order(from_amount=10.0)

        self.assertEqual(order['status'], 'awaiting_deposit')
        self.assertEqual(order['from_amount'], 10.0)
        self.assertAlmostEqual(order['to_amount'], 10.0 * RATE_KNF_TO_LTC)
        self.assertEqual(order['confirm_target'], 2)
        self.assertTrue(order['deposit_address'].startswith('knf1q'))
        self.assertGreater(order['expires_at'], order['created_at'])

    def test_deposit_addresses_are_unique_per_order(self):
        first = self.create_order()
        second = self.create_order()
        self.assertNotEqual(first['deposit_address'], second['deposit_address'])
        self.assertNotEqual(first['deposit_index'], second['deposit_index'])

    def test_rejects_unknown_asset(self):
        with self.assertRaises(ValidationError):
            self.create_order(from_asset='Dogecoin')

    def test_rejects_same_asset_pair(self):
        with self.assertRaises(ValidationError):
            self.create_order(from_asset=KNF, to_asset=KNF, destination='knf1qstudent')

    def test_rejects_amount_outside_limits(self):
        with self.assertRaises(ValidationError):
            self.create_order(from_amount=AMOUNT_LIMITS[KNF]['min'] / 100)
        with self.assertRaises(ValidationError):
            self.create_order(from_amount=AMOUNT_LIMITS[KNF]['max'] * 100)

    def test_rejects_non_numeric_amount(self):
        with self.assertRaises(ValidationError):
            self.create_order(from_amount='lots')

    def test_rejects_invalid_destination(self):
        # A KNF address is not valid on the LTC side of a KNF -> LTC order.
        with self.assertRaises(ValidationError):
            self.create_order(destination='knf1qwrongchain')

    def test_rejects_reserve_as_destination(self):
        with self.assertRaises(ValidationError):
            self.create_order(destination=self.ltc_wallet.reserve.address)

    def test_rejects_other_orders_deposit_address_as_destination(self):
        # An LTC -> KNF order's deposit address lives on the LTC chain; a
        # later KNF -> LTC order must not be allowed to pay out into it.
        ltc_order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0,
                                      destination='knf1qstudent')
        with self.assertRaises(ValidationError):
            self.create_order(destination=ltc_order['deposit_address'])

    def test_the_order_id_is_eight_uppercase_hex_digits(self):
        self.assertRegex(self.create_order()['id'], r'^[0-9A-F]{8}$')

    def test_an_order_starts_with_nothing_received_and_nothing_sent(self):
        order = self.create_order()

        self.assertEqual(order['pair'], 'KNF Coin -> LTC Testnet')
        self.assertEqual(order['rate'], RATE_KNF_TO_LTC)
        self.assertEqual(order['confirm_count'], 0)
        self.assertEqual(order['received_amount'], 0)
        self.assertEqual(order['deposit_scripthash'], self.knf_wallet.derive(order['deposit_index']).scripthash)
        for column in ('locked_rate', 'tx_deposit_id', 'tx_send_id', 'tx_send_raw', 'sweep_state', 'tx_sweep_id', 'error'):
            self.assertIsNone(order[column], column)

    def test_an_ltc_to_knf_order_takes_its_deposit_on_the_ltc_chain(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=2.0, destination='knf1qstudent')

        self.assertEqual(order['pair'], 'LTC Testnet -> KNF Coin')
        self.assertTrue(order['deposit_address'].startswith('tltc1q'))
        self.assertAlmostEqual(order['rate'], 1.0 / RATE_KNF_TO_LTC)
        self.assertAlmostEqual(order['to_amount'], 2.0 / RATE_KNF_TO_LTC)

    def test_inputs_are_trimmed_before_they_are_checked(self):
        order = self.service.create_order({
            'from_asset': '  KNF Coin ', 'to_asset': ' LTC Testnet', 'from_amount': ' 10 ', 'destination': '  tltc1qstudent  ',
        })

        self.assertEqual(order['from_asset'], KNF)
        self.assertEqual(order['to_asset'], LTC)
        self.assertEqual(order['from_amount'], 10.0)
        self.assertEqual(order['destination'], 'tltc1qstudent')

    def test_the_limits_themselves_are_accepted(self):
        sides = ((KNF, LTC, 'tltc1qstudent'), (LTC, KNF, 'knf1qstudent'))
        for from_asset, to_asset, destination in sides:
            for amount in (AMOUNT_LIMITS[from_asset]['min'], AMOUNT_LIMITS[from_asset]['max']):
                with self.subTest(asset=from_asset, amount=amount):
                    order = self.create_order(from_asset=from_asset, to_asset=to_asset,
                                              from_amount=amount, destination=destination)
                    self.assertEqual(order['from_amount'], amount)

    def test_a_numeric_string_is_taken_as_its_number(self):
        self.assertEqual(self.create_order(from_amount='10.5')['from_amount'], 10.5)

    def test_nan_and_infinity_are_outside_every_limit(self):
        for amount in ('nan', 'inf', '-inf'):
            with self.subTest(amount=amount):
                with self.assertRaises(ValidationError) as caught:
                    self.create_order(from_amount=amount)
                self.assertEqual(str(caught.exception), outside_the_limits(KNF))

    def test_each_refusal_is_a_sentence_the_student_can_act_on(self):
        # The SPA shows these word for word under the swap form
        cases = [
            ({'from_asset': None}, 'Unsupported asset: '),
            ({'from_asset': 'Dogecoin'}, 'Unsupported asset: Dogecoin'),
            ({'to_asset': 'Dogecoin'}, 'Unsupported asset: Dogecoin'),
            ({'to_asset': KNF, 'destination': 'knf1qstudent'}, 'Unsupported pair: KNF Coin -> KNF Coin'),
            ({'from_amount': None}, 'from_amount must be a number'),
            ({'from_amount': 'lots'}, 'from_amount must be a number'),
            ({'from_amount': AMOUNT_LIMITS[KNF]['min'] / 10}, outside_the_limits(KNF)),
            ({'from_amount': AMOUNT_LIMITS[KNF]['max'] + 0.01}, outside_the_limits(KNF)),
            ({'from_asset': LTC, 'to_asset': KNF, 'from_amount': AMOUNT_LIMITS[LTC]['max'] + 1, 'destination': 'knf1qstudent'},
             outside_the_limits(LTC)),
            ({'destination': 'knf1qwrongchain'}, 'Invalid LTC Testnet destination address'),
            ({'destination': None}, 'Invalid LTC Testnet destination address'),
            ({'destination': 'tltc1qreserve'}, 'Destination cannot be an exchange address - use your own wallet address'),
        ]
        for changes, message in cases:
            payload = {'from_asset': KNF, 'to_asset': LTC, 'from_amount': 10.0, 'destination': 'tltc1qstudent', **changes}
            with self.subTest(changes=changes):
                with self.assertRaises(ValidationError) as caught:
                    self.service.create_order(payload)
                self.assertEqual(str(caught.exception), message)

    def test_a_refused_order_leaves_no_trace(self):
        with self.assertRaises(ValidationError):
            self.create_order(from_amount=AMOUNT_LIMITS[KNF]['max'] * 5)

        self.assertEqual(self.service.list_orders(), [])
        self.assertEqual(self.create_order()['deposit_index'], 1)

    def test_deposit_indexes_start_at_one_and_never_repeat(self):
        indexes = [self.create_order()['deposit_index'] for _ in range(3)]
        self.assertEqual(indexes, [1, 2, 3])

    def test_concurrent_orders_never_share_a_deposit_address(self):
        # Several requests at once: the index allocation is the one place two
        # orders could end up paying into the same address
        indexes, errors = [], []

        def place_orders():
            try:
                for _ in range(5):
                    indexes.append(self.create_order()['deposit_index'])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=place_orders) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(30)

        self.assertEqual(errors, [])
        self.assertEqual(sorted(indexes), list(range(1, 41)))

    def test_an_order_expires_thirty_minutes_after_it_was_created(self):
        self.at(1_791_105_600_000)
        order = self.create_order()

        self.assertEqual(order['created_at'], 1_791_105_600_000)
        self.assertEqual(order['updated_at'], 1_791_105_600_000)
        self.assertEqual(order['expires_at'], 1_791_105_600_000 + 30 * 60 * 1000)








############################################################
# TestOrderRecords
############################################################
#
# Listing, reading and updating stored orders.
############################################################

class TestOrderRecords(ExchangeTestCase):

    def test_orders_are_listed_newest_first_up_to_the_limit(self):
        ids = []
        for minute in range(5):
            self.at(1_791_105_600_000 + minute * 60_000)
            ids.append(self.create_order()['id'])

        listed = [order['id'] for order in self.service.list_orders(3)]

        self.assertEqual(listed, ids[::-1][:3])

    def test_an_unknown_id_is_no_order(self):
        self.assertIsNone(self.service.get_order('NOPE1234'))

    def test_every_order_answer_carries_the_logos_of_its_two_coins(self):
        order = self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')

        for answer in (order, self.reload(order), self.service.list_orders(1)[0]):
            self.assertEqual(answer['from_icon'], '/api/exchange/icons/ltc4')
            self.assertEqual(answer['to_icon'], '/api/exchange/icons/knf')

    def test_a_coin_without_a_logo_file_is_answered_as_null(self):
        order = self.create_order()
        os.unlink(os.path.join(self.icons_dir, 'ltc4.svg'))

        answer = self.reload(order)

        self.assertEqual(answer['from_icon'], '/api/exchange/icons/knf')
        self.assertIsNone(answer['to_icon'])

    def test_a_logo_dropped_later_shows_on_the_orders_made_before_it(self):
        # The logos are looked up at every read, never stored with the order
        os.unlink(os.path.join(self.icons_dir, 'knf.svg'))
        order = self.create_order()
        self.assertIsNone(order['from_icon'])

        with open(os.path.join(self.icons_dir, 'knf.png'), 'wb') as logo:
            logo.write(b'\x89PNG')

        self.assertEqual(self.reload(order)['from_icon'], '/api/exchange/icons/knf')

    def test_every_update_moves_the_update_time_only(self):
        self.at(1_000)
        order = self.create_order()

        self.at(5_000)
        self.service.update_order(order['id'], {'error': 'Reserve address has no funds to pay out'})

        updated = self.reload(order)
        self.assertEqual(updated['error'], 'Reserve address has no funds to pay out')
        self.assertEqual(updated['updated_at'], 5_000)
        self.assertEqual(updated['created_at'], 1_000)








############################################################
# TestRates
############################################################
#
# The one pair priced, both ways, from the configuration at
# call time — and a syncing server's reserve reported as an
# error.
############################################################

class TestRates(ExchangeTestCase):

    def test_snapshot_pairs_are_reciprocal(self):
        snapshot = self.service.rates_snapshot()
        knf_ltc = snapshot['pairs'][f'{KNF}->{LTC}']
        ltc_knf = snapshot['pairs'][f'{LTC}->{KNF}']
        self.assertAlmostEqual(knf_ltc * ltc_knf, 1.0)

    def test_reserves_snapshot_reports_syncing_server_as_error(self):
        self.knf_wallet.tip_height = 0
        reserves = {r['network']: r for r in self.service.reserves_snapshot()}

        self.assertIsNotNone(reserves['knf']['error'])
        self.assertIsNone(reserves['knf']['confirmed'])
        self.assertIsNone(reserves['ltc4']['error'])

    def test_the_snapshot_carries_both_directions_and_the_enforced_limits(self):
        snapshot = self.service.rates_snapshot()

        self.assertEqual(snapshot['pairs'], {
            'KNF Coin->LTC Testnet': RATE_KNF_TO_LTC,
            'LTC Testnet->KNF Coin': 1.0 / RATE_KNF_TO_LTC,
        })
        self.assertEqual(snapshot['limits'], AMOUNT_LIMITS)

    def test_the_snapshot_carries_the_logo_of_each_asset(self):
        self.assertEqual(self.service.rates_snapshot()['icons'], {
            'KNF Coin': '/api/exchange/icons/knf',
            'LTC Testnet': '/api/exchange/icons/ltc4',
        })

    def test_an_asset_without_a_logo_file_is_advertised_as_null(self):
        os.unlink(os.path.join(self.icons_dir, 'knf.svg'))
        self.assertEqual(self.service.rates_snapshot()['icons'], {
            'KNF Coin': None,
            'LTC Testnet': '/api/exchange/icons/ltc4',
        })

    def test_only_the_one_pair_is_priced(self):
        self.assertEqual(self.service.pair_rate(KNF, LTC), RATE_KNF_TO_LTC)
        self.assertEqual(self.service.pair_rate(LTC, KNF), 1.0 / RATE_KNF_TO_LTC)
        with self.assertRaises(ValidationError) as caught:
            self.service.pair_rate(LTC, LTC)
        self.assertEqual(str(caught.exception), 'Unsupported pair: LTC Testnet -> LTC Testnet')

    def test_the_rate_follows_the_configuration_at_call_time(self):
        with patch('app.config.RATE_KNF_TO_LTC', 0.5):
            pairs = self.service.rates_snapshot()['pairs']

        self.assertEqual(pairs['KNF Coin->LTC Testnet'], 0.5)
        self.assertEqual(pairs['LTC Testnet->KNF Coin'], 2.0)

    def test_the_snapshot_says_what_each_reserve_can_still_pay_out(self):
        # Less the fee the payout costs the reserve
        self.knf_wallet.reserve_balance = 50 * COIN
        self.ltc_wallet.reserve_balance = 2 * COIN

        self.service.refresh_capacity()

        self.assertEqual(self.service.rates_snapshot()['capacity'], {
            'KNF Coin': (50 * COIN - 1410) / COIN,
            'LTC Testnet': (2 * COIN - 1410) / COIN,
        })

    def test_what_a_reserve_can_pay_out_is_unknown_until_read_and_while_it_cannot_be(self):
        self.assertEqual(self.service.rates_snapshot()['capacity'], {'KNF Coin': None, 'LTC Testnet': None})

        self.ltc_wallet.reserve_balance_sat = Mock(side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out'))
        self.service.refresh_capacity()

        capacity = self.service.rates_snapshot()['capacity']
        self.assertIsNone(capacity['LTC Testnet'])
        self.assertGreater(capacity['KNF Coin'], 0)

    def test_a_reserve_that_owes_more_than_it_holds_can_pay_out_nothing(self):
        self.ltc_wallet.reserve_balance = 2 * COIN
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN)
        self.worker._check_deposit(self.reload(order))
        self.ltc_wallet.reserve_balance = 0

        self.service.refresh_capacity()

        self.assertEqual(self.service.rates_snapshot()['capacity']['LTC Testnet'], 0.0)








############################################################
# TestReserves
############################################################
#
# Every chain's reserve with its balance in coins, or the
# reason it has none — one chain's failure never hiding the
# other's.
############################################################

class TestReserves(ExchangeTestCase):

    def test_every_chain_is_listed_with_its_reserve_and_balance_in_coins(self):
        self.knf_wallet.receive('reserve-scripthash', 'top-up-tx', 482150000000, height=90)
        self.ltc_wallet.receive('reserve-scripthash', 'change-tx', 104235, height=95)
        self.ltc_wallet.receive('reserve-scripthash', 'pending-top-up-tx', 40 * COIN)

        self.assertEqual(self.service.reserves_snapshot(), [
            {'network': 'knf', 'asset': KNF, 'short_name': 'KNF', 'full_name': 'KNF Coin',
             'block_explorer': '/explorer', 'icon': '/api/exchange/icons/knf', 'address': 'knf1qreserve',
             'confirmed': 4821.5, 'unconfirmed': 0.0, 'available': 4821.4999859, 'error': None},
            {'network': 'ltc4', 'asset': LTC, 'short_name': 'tLTC4', 'full_name': 'Litecoin Testnet4',
             'block_explorer': 'https://example.org', 'icon': '/api/exchange/icons/ltc4', 'address': 'tltc1qreserve',
             'confirmed': 0.00104235, 'unconfirmed': 40.0, 'available': 40.00102825, 'error': None},
        ])

    def test_what_a_reserve_owes_the_orders_paid_into_is_not_available(self):
        # 10 KNF paid into an order are owed 1.2345678 tLTC4, plus its payout's
        # fee; the new order's payout would cost another
        self.ltc_wallet.receive('reserve-scripthash', 'top-up-tx', 5 * COIN, height=90)
        order = self.create_order()
        self.fund_deposit(order, 10 * COIN)
        self.worker._check_deposit(self.reload(order))

        ltc = self.service.reserves_snapshot()[1]

        self.assertEqual(ltc['confirmed'], 5.0)
        self.assertEqual(ltc['available'], (5 * COIN - int(round(10 * RATE_KNF_TO_LTC * COIN)) - 2 * 1410) / COIN)

    def test_a_chain_without_a_logo_file_is_listed_with_a_null_icon(self):
        os.unlink(os.path.join(self.icons_dir, 'ltc4.svg'))

        icons = [reserve['icon'] for reserve in self.service.reserves_snapshot()]

        self.assertEqual(icons, ['/api/exchange/icons/knf', None])

    def test_a_syncing_server_is_named_as_the_reason_and_the_address_stays(self):
        self.knf_wallet.tip_height = 0
        knf = self.service.reserves_snapshot()[0]

        self.assertEqual(knf['error'], 'Electrum server is still syncing (no chain tip yet)')
        self.assertEqual(knf['address'], 'knf1qreserve')
        self.assertIsNone(knf['unconfirmed'])

    def test_a_chain_that_cannot_be_read_does_not_hide_the_other(self):
        unreachable = 'Electrum 127.0.0.1:1 unreachable: [Errno 111] Connection refused'
        self.ltc_wallet.get_tip_height = Mock(side_effect=ConnectionError(unreachable))

        knf, ltc = self.service.reserves_snapshot()

        self.assertEqual(ltc['error'], unreachable)
        self.assertIsNone(ltc['confirmed'])
        self.assertIsNone(ltc['available'])
        self.assertEqual(ltc['address'], 'tltc1qreserve')
        self.assertIsNone(knf['error'])
        self.assertEqual(knf['confirmed'], 0.0)








############################################################
# TestTheReserveCoversTheOrder
############################################################
#
# An order is only taken while the reserve of the chain the
# student receives on can cover its payout: what it holds,
# less what it owes the orders paid into before, less the
# payout's own fee. Refused, the student is told the most
# they can send; a reserve that cannot be read takes no order.
############################################################

class TestTheReserveCoversTheOrder(ExchangeTestCase):

    # What a 10 KNF order is paid, in tLTC4 satoshis, and the fee its payout
    # costs the reserve
    TEN_KNF = int(round(10 * RATE_KNF_TO_LTC * COIN))
    PAYOUT_FEE = 1410

    def owe_a_payout_on(self, order):
        # The student pays into the order: its payout is owed from now on
        self.fund_deposit(order, int(round(order['from_amount'] * COIN)))
        self.worker._check_deposit(self.reload(order))

    def test_an_order_the_reserve_can_cover_is_taken(self):
        self.ltc_wallet.reserve_balance = self.TEN_KNF + self.PAYOUT_FEE
        self.assertEqual(self.create_order(from_amount=10.0)['status'], 'awaiting_deposit')

    def test_one_it_cannot_cover_is_refused_with_the_most_it_can_take(self):
        self.ltc_wallet.reserve_balance = self.TEN_KNF + self.PAYOUT_FEE - 1

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_amount=10.0)

        self.assertEqual(str(caught.exception), 'The exchange can take at most 9.99999991 KNF Coin right now')

    def test_a_reserve_too_low_for_the_smallest_order_takes_none(self):
        # Half of what the smallest order is paid to spare
        smallest = AMOUNT_LIMITS[KNF]['min']
        self.ltc_wallet.reserve_balance = int(smallest * RATE_KNF_TO_LTC * COIN / 2) + self.PAYOUT_FEE

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_amount=smallest)

        self.assertEqual(str(caught.exception), 'The exchange cannot pay out LTC Testnet right now - please try again later')

    def test_the_reserve_asked_is_the_one_of_the_chain_the_student_receives_on(self):
        self.knf_wallet.reserve_balance = 0
        self.assertEqual(self.create_order()['status'], 'awaiting_deposit')

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_asset=LTC, to_asset=KNF, from_amount=1.0, destination='knf1qstudent')
        self.assertEqual(str(caught.exception), 'The exchange cannot pay out KNF Coin right now - please try again later')

    def test_a_payout_owed_to_an_order_paid_into_is_not_promised_again(self):
        # Two orders fit while neither is paid into; once one is, the payout
        # it is owed no longer counts as spare
        self.ltc_wallet.reserve_balance = 2 * COIN
        first = self.create_order(from_amount=10.0)
        self.create_order(from_amount=10.0)
        self.owe_a_payout_on(first)

        with self.assertRaises(ValidationError) as caught:
            self.create_order(from_amount=10.0)

        # 2 tLTC4 less the 1.2345819 owed and the new payout's fee: 0.765404 tLTC4
        self.assertEqual(str(caught.exception), 'The exchange can take at most 6.1997729 KNF Coin right now')

    def test_what_an_order_owes_follows_its_stage(self):
        # Confirming: what its coins fetch now; locked: what it locked; its
        # payout out, or its coins on their way back: nothing more
        self.ltc_wallet.reserve_balance = 10 * COIN
        order = self.create_order(from_amount=10.0)
        self.owe_a_payout_on(order)
        owed = self.TEN_KNF + self.PAYOUT_FEE
        self.assertEqual(self.service.owed_sat('ltc4'), owed)

        self.service.update_order(order['id'], {'status': 'sending', 'to_amount': 2.0})
        self.assertEqual(self.service.owed_sat('ltc4'), 2 * COIN + self.PAYOUT_FEE)

        self.service.update_order(order['id'], {'tx_send_raw': 'payout-raw-hex'})
        self.assertEqual(self.service.owed_sat('ltc4'), 0)

        self.service.update_order(order['id'], {'status': 'refunding', 'tx_send_raw': None})
        self.assertEqual(self.service.owed_sat('ltc4'), 0)
        self.assertEqual(self.service.owed_sat('knf'), 0)

    def test_a_reserve_that_cannot_be_read_takes_no_order(self):
        self.ltc_wallet.reserve_balance_sat = Mock(side_effect=ConnectionError('Electrum 127.0.0.1:1 unreachable: timed out'))

        with self.assertLogs('exchange.service', 'WARNING') as logs:
            with self.assertRaises(Unavailable) as caught:
                self.create_order()

        self.assertEqual(str(caught.exception), 'The exchange cannot check its LTC Testnet reserve right now - please try again in a minute')
        self.assertIn('unreachable: timed out', '\n'.join(logs.output))
        self.assertEqual(self.service.list_orders(), [])

    def test_a_refused_order_takes_no_deposit_address(self):
        self.ltc_wallet.reserve_balance = 0
        with self.assertRaises(ValidationError):
            self.create_order()

        self.ltc_wallet.reserve_balance = 10 * COIN
        self.assertEqual(self.create_order()['deposit_index'], 1)








############################################################
# TestWallets
############################################################
#
# The chain wallets built on first use, and the reserve
# addresses logged for the operator.
############################################################

class TestWallets(ExchangeTestCase):

    def test_a_chain_wallet_is_built_once_on_first_use(self):
        service = ExchangeService(TEST_CHAINS)
        with patch('app.service.ExchangeWallet', side_effect=lambda chain: SimpleNamespace(chain=chain)) as build:
            first = service.wallet_for('knf')
            second = service.wallet_for_asset(KNF)

        self.assertEqual(build.call_count, 1)
        self.assertIs(first, second)
        self.assertIs(first.chain, TEST_CHAINS['knf'])

    def test_an_asset_the_exchange_does_not_trade_has_no_wallet(self):
        with self.assertRaises(ValidationError) as caught:
            self.service.wallet_for_asset('Dogecoin')
        self.assertEqual(str(caught.exception), 'Unsupported asset: Dogecoin')

    def test_the_reserve_addresses_are_logged_for_the_operator(self):
        with self.assertLogs('exchange.service', 'INFO') as logs:
            self.service.log_reserve_addresses()

        output = '\n'.join(logs.output)
        self.assertIn('knf1qreserve', output)
        self.assertIn('tltc1qreserve', output)

    def test_a_wallet_that_cannot_be_built_is_logged_not_fatal(self):
        service = ExchangeService(TEST_CHAINS)
        failure = ValueError('EXCHANGE_PRIVATE_KEY environment variable not set')
        with patch('app.service.ExchangeWallet', side_effect=failure):
            with self.assertLogs('exchange.service', 'ERROR') as logs:
                service.log_reserve_addresses()

        self.assertEqual(len(logs.output), 2)
        self.assertTrue(all('could not derive reserve address' in line for line in logs.output))
