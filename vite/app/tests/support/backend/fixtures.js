// -----------------------------------------------------------
//  [*] Test support — canonical backend answers
//
//  One realistic body per endpoint the SPA calls, in the
//  exact shape the backend answers with — built from the
//  backend's own code: rates_snapshot and reserves_snapshot
//  in service.py, and the orders table, every column of a row
//  as the service hands it over (deposit_index, tx_send_raw,
//  paid_coins and the sweep columns included, though no page
//  reads them) with the logos of its two coins and its
//  refunds. The answers agree with each other: every coin has
//  the same logo in every answer, every order is priced at
//  the rates' KNF Coin → LTC Testnet rate (RATE_KNF_LTC's
//  default) or its inverse, every deposit address lies on the
//  chain the student pays from and every destination on the
//  chain they receive on, the addresses are valid bech32
//  P2WPKH addresses of their chains with the Electrum
//  scripthashes that belong to them, the completed payout's
//  txid is the hash of its raw transaction, what each reserve
//  has available — and the rates' capacity — is its balance
//  less the payouts the orders paid into are owed and a
//  payout's fee, and the order sending its coins back is the
//  one the tLTC4 reserve could not cover.
//
//  The orders cover the whole lifecycle — one per status the
//  worker writes, newest first, the way GET
//  /api/exchange/orders lists them; the two whose coins went
//  back carry their refunds. Times are those of a
//  classroom morning (NOW); a test that reads a countdown or a
//  creation time freezes the clock there.
//
//  handlers.js serves these by default; a test that needs a
//  variation copies a fixture and edits the copy rather than
//  changing a fixture other tests share — the builders hand
//  out a fresh copy on every call.
//
//  Used by:
//    - handlers.js — the default handlers
//    - the tests — the values they assert on, and the rows
//      they vary
// -----------------------------------------------------------

// The two assets, labelled exactly as the frontend and the
// backend's ASSET_TO_NETWORK label them
export const KNF = 'KNF Coin'
export const LTC = 'LTC Testnet'

// Each coin's logo, as the backend advertises it: its icon
// route, named by the coin's network
export const ICONS = {
  [KNF]: '/api/exchange/icons/knf',
  [LTC]: '/api/exchange/icons/ltc4',
}

// The exchange's reserve (payout) wallets, one per chain
export const RESERVE_KNF = 'knf1q9sxuzntyg6znp5a7kj4jq7f97fjfshp4tpc3xu'
export const RESERVE_LTC = 'tltc1qxcvrlaedg3j5yvp85sla2y39ddknshhw00y5f2'

// A student's own wallets — where the payouts go
export const STUDENT_KNF = 'knf1qpuay0k96v06tzhk6g8f50evc2wk7gp09pk8nka'
export const STUDENT_LTC = 'tltc1qqjw4t9e0yp9ghn5mm3hpudept066fu22pnx3nu'

// The moment the fixtures describe: 2026-10-04 09:20 UTC,
// 12:20 in Vilnius
export const NOW = 1791105600000

// How long a new order waits for its deposit (ORDER_TTL_MS)
export const ORDER_TTL_MS = 30 * 60 * 1000







// -----------------------------------------------------------
// Rates — GET /api/exchange/rates
// -----------------------------------------------------------
//
// The rates answer, and the two prices it carries.
// -----------------------------------------------------------

// The KNF → tLTC4 price and its inverse, as Python's float
// division prints it
export const RATE_KNF_LTC = 0.12345678
export const RATE_LTC_KNF = 8.100000664200055

// What each reserve can still pay out to a new order, in
// whole coins: its balance, less the payouts owed to the
// orders paid into (the confirming LTC Testnet one on KNF;
// the exchanging and the sending one on tLTC4) and the fee of
// the new payout — the reserves' available, the rates'
// capacity
export const AVAILABLE = {
  [KNF]: 4817.44997147,
  [LTC]: 135.3713708,
}

// The live rates, the per-asset limits the backend enforces
// (AMOUNT_LIMITS) — a whole-number limit, which Python prints
// with its ".0", arrives in JavaScript as a whole number —
// each asset's logo, and what the exchange can still pay out
// of each (more than the largest order needs)
export const rates = {
  pairs: {
    'KNF Coin->LTC Testnet': RATE_KNF_LTC,
    'LTC Testnet->KNF Coin': RATE_LTC_KNF,
  },
  limits: {
    'KNF Coin': { min: 0.001, max: 1000 },
    'LTC Testnet': { min: 0.0001, max: 100 },
  },
  icons: {
    'KNF Coin': ICONS[KNF],
    'LTC Testnet': ICONS[LTC],
  },
  capacity: {
    'KNF Coin': AVAILABLE[KNF],
    'LTC Testnet': AVAILABLE[LTC],
  },
}







// -----------------------------------------------------------
// Reserves — GET /api/exchange/reserves
// -----------------------------------------------------------
//
// The reserves answer: a balance per chain, and the two
// reasons the backend gives instead of one.
// -----------------------------------------------------------

// The two reasons reserves_snapshot reports instead of a
// balance: an Electrum server without a chain tip, and one
// that cannot be reached
export const RESERVE_SYNCING = 'Electrum server is still syncing (no chain tip yet)'
export const RESERVE_UNREACHABLE = 'Electrum 158.129.172.247:50002 unreachable: [Errno 111] Connection refused'

// Every chain's reserve wallet with its live balance in whole
// coins. The tLTC4 reserve has almost run dry — it could not
// cover the order now sending its coins back — and a top-up
// is on its way, still unconfirmed
export const reserves = () => [
  {
    network: 'knf',
    asset: KNF,
    short_name: 'KNF',
    full_name: 'KNF Coin',
    block_explorer: '/explorer',
    icon: ICONS[KNF],
    address: RESERVE_KNF,
    confirmed: 4821.5,
    unconfirmed: 0,
    available: AVAILABLE[KNF],
    error: null,
  },
  {
    network: 'ltc4',
    asset: LTC,
    short_name: 'tLTC4',
    full_name: 'Litecoin Testnet4',
    block_explorer: 'https://litecoinspace.org/testnet',
    icon: ICONS[LTC],
    address: RESERVE_LTC,
    confirmed: 0.00104235,
    unconfirmed: 140,
    available: AVAILABLE[LTC],
    error: null,
  },
]







// -----------------------------------------------------------
// Orders — GET /api/exchange/orders[/<id>]
// -----------------------------------------------------------
//
// One order per status, newest first, and the ids that name
// them.
// -----------------------------------------------------------

// Order ids, the backend's uuid4().hex[:8].upper()
export const AWAITING_ID = 'E9D2C410'
export const CONFIRMING_ID = '5C8F0A3B'
export const EXCHANGING_ID = '91AA7E06'
export const REFUNDING_ID = 'A61F3D08'
export const SENDING_ID = '2D6B4F98'
export const COMPLETED_ID = '7F3A9C21'
export const REFUNDED_ID = 'D47C2E95'
export const EXPIRED_ID = 'B04E1D77'
export const FAILED_ID = 'C3E15A0F'
export const REVERSED_ID = '6E1B90D4'
export const NEW_ORDER_ID = '4AE07B12'

// What the worker recorded on the orders that went wrong: a
// payout that could not get out yet, two that could not be
// made — the coins sent back — and one too small to pay out
// or send back
export const PAYOUT_PENDING = 'Electrum 158.129.172.247:50002 unreachable: timed out'
export const REFUND_SHORTFALL = "The exchange's LTC Testnet reserve could not cover the payout of 185.18517 LTC Testnet"
export const REFUND_DUST = "Received amount is too small to pay out (a payout of 0.0000037 LTC Testnet is below the network's minimum of 0.00000547 LTC Testnet)"
export const DUST_FAILURE = "Received amount is too small to pay out (a payout of 0.00000123 LTC Testnet is below the network's minimum of 0.00000547 LTC Testnet)"

// The refunds of the two orders whose coins went back: one
// still confirming, one confirmed
export const REFUND_PENDING_TXID = 'f929e35dfdc79e1dd652a917e67406a06d51e72daf114ff324448501e0312e3c'
export const REFUND_CONFIRMED_TXID = '791285e062ef6948de92286ab8ff1745de6ea88b59842e73786205f2e2a13c02'

// The completed order's payout: the signed transaction the
// worker persisted before broadcasting it, and its txid
export const PAYOUT_TXID = '841bdfa53049c32d3be7b6f5088b92b04d6d3c520f268c1c87c75fcd3c78ea8a'
const PAYOUT_RAW = '0200000000010140daaa50bb33e6e72743d45920f73351c680496853ab829a24e99a11700224d50100000000ffffffff027802964900000000160014049d55972f204a8bce9bdc6e1e37215bf5a4f14a8ef5f7600000000016001436183ff72d4465423027a43fd512256b6d385eee02473044022052f22665a60c12d289185d950ee8813609166f6b113d178d6c0fd3901ff239a10220a095f20f9395650cf9380b8edb224a6b248a1e924e8fd0ae2e1a9492a3305f180121028cb610900f9e347fae886dc6507795ec745c4c3fcb2eb2c73e14934c867ee05700000000'

// The columns every order row shares before the worker
// touches it
const FRESH = {
  locked_rate: null,
  paid_coins: null,
  confirm_target: 2,
  confirm_count: 0,
  received_amount: 0,
  tx_deposit_id: null,
  tx_send_id: null,
  tx_send_raw: null,
  sweep_state: null,
  tx_sweep_id: null,
  error: null,
  refunds: [],
}

// One row per status, newest first
const ROWS = [

  // Waiting for the student's 10 KNF — 25 minutes left at NOW
  {
    ...FRESH,
    id: AWAITING_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 10,
    to_amount: 1.2345678,
    rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'awaiting_deposit',
    deposit_index: 49,
    deposit_address: 'knf1qp3q7agmp0sjt6g6tg6dd07c77ptqv44hpjrt22',
    deposit_scripthash: 'db328d87719102ebbef426ce4b704a9408000c5a9468f152fbdc7cb50f759b3b',
    created_at: 1791105300000,
    updated_at: 1791105300000,
    expires_at: 1791107100000,
  },

  // 0.5 tLTC4 arrived, one of its two confirmations seen
  {
    ...FRESH,
    id: CONFIRMING_ID,
    pair: 'LTC Testnet -> KNF Coin',
    from_asset: LTC,
    to_asset: KNF,
    from_amount: 0.5,
    to_amount: 4.050000332100027,
    rate: RATE_LTC_KNF,
    destination: STUDENT_KNF,
    status: 'awaiting_confirmations',
    confirm_count: 1,
    deposit_index: 48,
    deposit_address: 'tltc1qe5djred7q7x6uwxnhx3y2r838x4suhfql9rrng',
    deposit_scripthash: '07a95981c38705e51c5f16a70af59f61741e0a519eebe1b07ebc603ef5a263e6',
    received_amount: 0.5,
    tx_deposit_id: '49c1b144e280b8429ee1c44d3f5ac2628875c5a9e4a876d9da62f4df54681ced',
    created_at: 1791104700000,
    updated_at: 1791105580000,
    expires_at: 1791106500000,
  },

  // 25 KNF confirmed, the rate not locked yet
  {
    ...FRESH,
    id: EXCHANGING_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 25,
    to_amount: 3.0864195,
    rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'exchanging',
    confirm_count: 2,
    deposit_index: 47,
    deposit_address: 'knf1qxl2r02jd4fakclvlcun0svga5r2ac63hu02dv5',
    deposit_scripthash: 'c3f5527b956ae53c95ef4592c9f954643cd373d125ea29229a9d848ce5e0f549',
    received_amount: 25,
    tx_deposit_id: '7e0ef8790435a0e7a3e0593328d437932040be678010c5ec55cfccb4d4056665',
    created_at: 1791103800000,
    updated_at: 1791105595000,
    expires_at: 1791105600000,
  },

  // 10 KNF agreed, 1500 sent: worth 185.18517 tLTC4, more than
  // the tLTC4 reserve could cover — the coins are on their way
  // back to the student's wallet, the network fee taken off
  {
    ...FRESH,
    id: REFUNDING_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 10,
    to_amount: 185.18517,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'refunding',
    confirm_count: 2,
    deposit_index: 46,
    deposit_address: 'knf1q9twftgy0xh2w8sx9k4u29kpdllah7hahvyjmfx',
    deposit_scripthash: 'c0c1d82a1857d61f10b78e3225ad79956327d1c2bf045eb9d688489d4abdba63',
    received_amount: 1500,
    tx_deposit_id: '89283ee9da8ef8b97d0b17d801ebf2d6d36bdc73f5e425d756f7becb5865229f',
    error: REFUND_SHORTFALL,
    refunds: [
      {
        txid: REFUND_PENDING_TXID,
        confirmed: false,
        created_at: 1791105540000,
        recipients: [{ address: STUDENT_KNF, amount: 1499.999989 }],
      },
    ],
    created_at: 1791103200000,
    updated_at: 1791105540000,
    expires_at: 1791105000000,
  },

  // 10 KNF agreed, 12.5 sent: the payout was rescaled to the
  // deposit, and has not got out yet — the tLTC4 Electrum
  // server could not be reached
  {
    ...FRESH,
    id: SENDING_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 10,
    to_amount: 1.54320975,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'sending',
    confirm_count: 2,
    deposit_index: 45,
    deposit_address: 'knf1qqv5jtyu7k9t6rxvpezp5656mdjj65347nntk2x',
    deposit_scripthash: 'cab9104ecb617c945d916e75ea22df00439e65e0f2bb675e5a65c3ed505cecdc',
    received_amount: 12.5,
    tx_deposit_id: 'f544662be209c1de2610b815c35955d30a8e80e49ffaf94fb1b5d1537d189951',
    paid_coins: '["f544662be209c1de2610b815c35955d30a8e80e49ffaf94fb1b5d1537d189951:0"]',
    error: PAYOUT_PENDING,
    created_at: 1791102600000,
    updated_at: 1791105570000,
    expires_at: 1791104400000,
  },

  // Yesterday's 100 KNF swap, paid out and swept into the
  // reserve
  {
    ...FRESH,
    id: COMPLETED_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 100,
    to_amount: 12.345678,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'completed',
    confirm_count: 2,
    deposit_index: 44,
    deposit_address: 'knf1qxjg9pc8ddsxcxrag5ahg8a62wmx5mwudwzjv2z',
    deposit_scripthash: 'ed617934a077d16392a0d31fcfb441901375132341356f1a803087b7b4eb5c9b',
    received_amount: 100,
    tx_deposit_id: 'e580d9e28b39c2724bb37bef433322eace1e14726d3cdb5d7d39b2038178c84c',
    paid_coins: '["e580d9e28b39c2724bb37bef433322eace1e14726d3cdb5d7d39b2038178c84c:0"]',
    tx_send_id: PAYOUT_TXID,
    tx_send_raw: PAYOUT_RAW,
    sweep_state: 'swept',
    tx_sweep_id: 'b5d805a241a66a968fe34a14a5592c3f13dd9ce57bda24b920a1ebedb59b071f',
    created_at: 1791045600000,
    updated_at: 1791046880000,
    expires_at: 1791047400000,
  },

  // 0.001 KNF agreed, 0.00003 sent: a payout of 370 sat is
  // below the dust limit, but the deposit was worth sending
  // back — 1900 sat once the network fee was taken off
  {
    ...FRESH,
    id: REFUNDED_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 0.001,
    to_amount: 0.0000037037034,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'refunded',
    confirm_count: 2,
    deposit_index: 43,
    deposit_address: 'knf1q8hgzdxtay8a72rqe8rt0eqp6m4uj06hyjje5ah',
    deposit_scripthash: 'b397e44fa5a886d03b1bc3354568a064817ad0d6afe605f815415460c7442bd3',
    received_amount: 0.00003,
    tx_deposit_id: 'aa1664bd5cf969904bde3ae9d3aa6a9aa196aa30431074518bb2600f2f90a7a0',
    error: REFUND_DUST,
    refunds: [
      {
        txid: REFUND_CONFIRMED_TXID,
        confirmed: true,
        created_at: 1791041400000,
        recipients: [{ address: STUDENT_KNF, amount: 0.000019 }],
      },
    ],
    created_at: 1791040800000,
    updated_at: 1791041700000,
    expires_at: 1791042600000,
  },

  // 1 tLTC4 that never came
  {
    ...FRESH,
    id: EXPIRED_ID,
    pair: 'LTC Testnet -> KNF Coin',
    from_asset: LTC,
    to_asset: KNF,
    from_amount: 1,
    to_amount: 8.100000664200055,
    rate: RATE_LTC_KNF,
    destination: STUDENT_KNF,
    status: 'expired',
    deposit_index: 42,
    deposit_address: 'tltc1q62rmzn5qma2eretxw9ug4luxfwllke94q0j0uh',
    deposit_scripthash: '9186f23c71ecb42b3fa920d7f369d3096f89d8062f1408086fb1ca2f6a6436fb',
    created_at: 1791036600000,
    updated_at: 1791038403000,
    expires_at: 1791038400000,
  },

  // 0.001 KNF agreed, 0.00001 sent: a payout of 123 sat is
  // below the dust limit, and a refund's fee would eat all of
  // it — so the order failed, its coins left where they are
  {
    ...FRESH,
    id: FAILED_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 0.001,
    to_amount: 0.0000012345678,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'failed',
    confirm_count: 2,
    deposit_index: 41,
    deposit_address: 'knf1qwxccmdhjtl8vtds8x580l89jetkf0923t7jx4l',
    deposit_scripthash: '31e9dd7d7d77fe2ea724a076ed7e1e1afb7dcac6317fbb2c8d879a73b2f098a9',
    received_amount: 0.00001,
    tx_deposit_id: 'c0d583f95797d4a172ae28c4691cf786e5548584c0431cc7981d6a3894647a1a',
    error: DUST_FAILURE,
    created_at: 1791026700000,
    updated_at: 1791027670000,
    expires_at: 1791028500000,
  },

  // 50 KNF swapped, paid out and swept — and then a
  // reorganisation of the KNF chain took the deposit (and the
  // sweep that spent it) back out of the chain
  {
    ...FRESH,
    id: REVERSED_ID,
    pair: 'KNF Coin -> LTC Testnet',
    from_asset: KNF,
    to_asset: LTC,
    from_amount: 50,
    to_amount: 6.172839,
    rate: RATE_KNF_LTC,
    locked_rate: RATE_KNF_LTC,
    destination: STUDENT_LTC,
    status: 'reversed',
    confirm_count: 2,
    deposit_index: 40,
    deposit_address: 'knf1q956y92pft3jy6f345y3tkhqmrm4xs7etxm0nqa',
    deposit_scripthash: 'cb05bea0edda6b1502b402fe63e4e6a6da92ae3aad4b970d4ec7d1d4f521fc1f',
    received_amount: 50,
    tx_deposit_id: 'c9c250c65487acd29776e4b85e96169082c3127cfe8291be9f6fcdbe39a1b48e',
    paid_coins: '["c9c250c65487acd29776e4b85e96169082c3127cfe8291be9f6fcdbe39a1b48e:0"]',
    tx_send_id: '7fca6e65dd11e75eaf901a70da55f291ea77ade837e9ac8fa4c7ea4f0e3ed538',
    sweep_state: 'swept',
    tx_sweep_id: '8c8672d5dfd5773e6ef122b853f6fa16c51e70b0d6bd570139c1b9e024a6b491',
    created_at: 1791019800000,
    updated_at: 1791023400000,
    expires_at: 1791021600000,
  },
]

// A row as the backend answers it: its columns, plus the logos
// of the two coins it trades, which the service adds at every
// read
const withIcons = (row) => ({ ...row, from_icon: ICONS[row.from_asset] ?? null, to_icon: ICONS[row.to_asset] ?? null })

// Every row, newest first — a fresh copy on every call
export const orders = () => structuredClone(ROWS).map(withIcons)







// -----------------------------------------------------------
// A new order — POST /api/exchange/orders
// -----------------------------------------------------------
//
// The swap form's default request, and the order the backend
// answers it with.
// -----------------------------------------------------------

// The request a student makes on the swap form by default:
// 10 KNF Coin for LTC Testnet, paid out to their own wallet
export const NEW_ORDER_REQUEST = { from_asset: KNF, to_asset: LTC, from_amount: 10, destination: STUDENT_LTC }

// The price of each pair the backend trades
const PAIR_RATES = {
  'KNF Coin->LTC Testnet': RATE_KNF_LTC,
  'LTC Testnet->KNF Coin': RATE_LTC_KNF,
}

// The deposit address the new order gets on each chain (HD
// child 50 — the next free index after the rows above)
const NEW_DEPOSITS = {
  [KNF]: { address: 'knf1qc52648uukkprt8wd950xqxh0ugdtvl93rh57gf', scripthash: 'a113dc1e87e859bcd4fcbdda7458b09163e60b212bf97adcc88a0a8b7a96f61d' },
  [LTC]: { address: 'tltc1qvasn8xfd8glj9sskgzax9pa0kwy3duyl7x9cmm', scripthash: '9b4e95bd8d13402197afe779200cbdc33f26b41d0aca9d04c0abb26775fe2caf' },
}

// A number as Python's str() prints a float: a whole number
// keeps its ".0"
const pythonFloat = (value) => (Number.isInteger(value) ? `${value}.0` : `${value}`)

// The backend's refusals of a new order, word for word — the
// limits of the rates above, printed the way Python prints a
// float
export const AMOUNT_REFUSALS = Object.fromEntries(Object.entries(rates.limits).map(([asset, { min, max }]) => (
  [asset, `Amount must be between ${pythonFloat(min)} and ${pythonFloat(max)} ${asset}`]
)))
export const invalidDestination = (asset) => `Invalid ${asset} destination address`
export const EXCHANGE_ADDRESS_REFUSAL = 'Destination cannot be an exchange address - use your own wallet address'
export const CREATE_FAILURE = 'Internal error creating order'

// The refusals of an order its reserve cannot cover: the most
// the student can send instead (as the backend prints it, at
// most 8 decimals) — or, when even the smallest order is too
// much, that the exchange cannot pay that asset out now — and
// the 503 of a reserve that cannot be read
export const capacityRefusal = (most, asset) => `The exchange can take at most ${most} ${asset} right now`
export const cannotPayOut = (asset) => `The exchange cannot pay out ${asset} right now - please try again later`
export const reserveUnreadable = (asset) => `The exchange cannot check its ${asset} reserve right now - please try again in a minute`







// -----------------------------------------------------------
// createdOrder
// -----------------------------------------------------------
//
// The row create_order stores and answers with for a request
// the backend accepted — the canonical request unless the
// test passes its own: awaiting its deposit on a fresh
// address of the chain the student pays from, priced at the
// pair's rate, created at the current clock (frozen by the
// tests that read it) and expiring ORDER_TTL_MS later. The
// amount is taken as a number, the way the backend's float()
// takes it.
//
// Used by:
//   - handlers.js — the POST answer, and the GET answer for
//     NEW_ORDER_ID
//   - the swap form and App tests — the order they land on
// -----------------------------------------------------------

export function createdOrder(request = NEW_ORDER_REQUEST) {

  const now = Date.now()
  const rate = PAIR_RATES[`${request.from_asset}->${request.to_asset}`]
  const amount = Number(request.from_amount)
  const deposit = NEW_DEPOSITS[request.from_asset]

  return withIcons({
    ...FRESH,
    id: NEW_ORDER_ID,
    pair: `${request.from_asset} -> ${request.to_asset}`,
    from_asset: request.from_asset,
    to_asset: request.to_asset,
    from_amount: amount,
    to_amount: amount * rate,
    rate,
    destination: request.destination,
    status: 'awaiting_deposit',
    deposit_index: 50,
    deposit_address: deposit.address,
    deposit_scripthash: deposit.scripthash,
    created_at: now,
    updated_at: now,
    expires_at: now + ORDER_TTL_MS,
  })
}







// -----------------------------------------------------------
// orderById
// -----------------------------------------------------------
//
// A fresh copy of the row with the given id — the new order
// as the canonical request created it for NEW_ORDER_ID — or
// nothing for an id the backend does not know, which the
// handler answers with its 404.
//
// Used by:
//   - handlers.js — GET /api/exchange/orders/<id>
//   - the order page tests — the row to vary
// -----------------------------------------------------------

export function orderById(id) {
  if (id === NEW_ORDER_ID) return createdOrder()
  return orders().find((row) => row.id === id) ?? null
}
