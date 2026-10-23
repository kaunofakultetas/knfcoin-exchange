// -----------------------------------------------------------
//  [*] Test support — default handlers for every UI endpoint
//
//  The happy path of the whole backend as the SPA sees it: one
//  msw handler per endpoint the code under src/ calls,
//  answering the fixtures. The handlers behave like the
//  backend where a page depends on it: the order list honours
//  ?limit= the way routes.py reads it (20 when missing or not
//  a number, clamped to 1..100), an unknown order id is the
//  backend's 404 "Not found", and a new order is checked in
//  create_order's order with its own sentences — an unknown
//  asset or pair, an amount that is not a number or outside
//  the limits, a destination that is not an address of the
//  receiving chain or belongs to the exchange, a payout more
//  than the receiving reserve can cover (the rates' capacity)
//  — before it is created with status 201.
//
//  Keep this in step with the SPA: the structural test
//  (tests/core/structural.test.js) extracts every backend call
//  from src/ and fails when one has no handler here — the
//  double must never fall behind the frontend it stands in
//  for.
//
//  Used by:
//    - server.js — the msw server starts from these handlers
//    - core/structural.test.js — every backend call of src/
//      must have one here
// -----------------------------------------------------------

import { http, HttpResponse } from 'msw'
import * as f from './fixtures'
import { TEST_ORIGIN } from '../location'


const abs = (path) => `${TEST_ORIGIN}${path}`
const refuse = (message, status = 400) => HttpResponse.json({ error: message }, { status })

// The assets the backend trades (ASSET_TO_NETWORK) — anything
// else is refused
const ASSETS = [f.KNF, f.LTC]

// The shape of a P2WPKH address on each chain: bech32 with
// the chain's prefix, witness version 0, a 20-byte program.
// The double checks the shape, not the checksum
const ADDRESS_SHAPES = {
  [f.KNF]: /^knf1q[02-9ac-hj-np-z]{38}$/,
  [f.LTC]: /^tltc1q[02-9ac-hj-np-z]{38}$/,
}

// Addresses the exchange controls, which a payout must never
// go to: the reserves and every order's deposit address
const EXCHANGE_ADDRESSES = new Set([f.RESERVE_KNF, f.RESERVE_LTC, ...f.orders().map((row) => row.deposit_address)])

// ?limit= read the way routes.py reads it
const listLimit = (request) => {
  const raw = new URL(request.url).searchParams.get('limit')
  const limit = raw !== null && /^\s*[+-]?\d+\s*$/.test(raw) ? parseInt(raw, 10) : 20
  return Math.max(1, Math.min(limit, 100))
}

// An amount the way the backend's format_coins prints it: at
// most 8 decimals, no trailing zeros
const formatCoins = (amount) => amount.toFixed(8).replace(/0+$/, '').replace(/\.$/, '')

// What Python's float() makes of the amount: a number, a
// numeric string, nan / inf (which no limit admits), or
// nothing for anything else
const pythonFloat = (value) => {
  if (typeof value === 'number' || typeof value === 'boolean') return Number(value)
  if (typeof value !== 'string') return null
  if (/^\s*[+-]?(\d+(\.\d*)?|\.\d+)(e[+-]?\d+)?\s*$/i.test(value)) return Number(value)
  if (/^\s*[+-]?(nan|inf|infinity)\s*$/i.test(value)) return Number.NaN
  return null
}







// -----------------------------------------------------------
// refusalOf
// -----------------------------------------------------------
//
// create_order's checks in the backend's own order, over the
// payload as request.get_json(silent=True) leaves it: the
// sentence of the first check that fails, or nothing when the
// order can be created — then with the trimmed fields and the
// amount as a number, the way create_order stores them. A
// field that is not text where the backend calls .strip() on
// it is the 500 that crash becomes in routes.py.
//
// Used by:
//   - defaultHandlers (below) — POST /api/exchange/orders
// -----------------------------------------------------------

function refusalOf(payload) {

  const fields = ['from_asset', 'to_asset', 'destination'].map((key) => payload[key] || '')
  if (fields.some((value) => typeof value !== 'string')) return { status: 500, message: f.CREATE_FAILURE }
  const [from, to, destination] = fields.map((value) => value.trim())


  if (!ASSETS.includes(from)) return { message: `Unsupported asset: ${from}` }
  if (!ASSETS.includes(to)) return { message: `Unsupported asset: ${to}` }
  if (from === to) return { message: `Unsupported pair: ${from} -> ${to}` }

  const amount = pythonFloat(payload.from_amount)
  if (amount === null) return { message: 'from_amount must be a number' }

  const limits = f.rates.limits[from]
  if (!(limits.min <= amount && amount <= limits.max)) return { message: f.AMOUNT_REFUSALS[from] }

  if (!ADDRESS_SHAPES[to].test(destination)) return { message: f.invalidDestination(to) }
  if (EXCHANGE_ADDRESSES.has(destination)) return { message: f.EXCHANGE_ADDRESS_REFUSAL }

  // The quote, against what the receiving reserve can still pay
  // out — in satoshis, the most offered rounded down to one
  const rate = f.rates.pairs[`${from}->${to}`]
  const capacitySat = Math.round(f.rates.capacity[to] * 1e8)
  if (Math.round(amount * rate * 1e8) > capacitySat) {
    const most = Math.floor(capacitySat / rate) / 1e8
    return { message: most < limits.min ? f.cannotPayOut(to) : f.capacityRefusal(formatCoins(most), from) }
  }


  return { accepted: { from_asset: from, to_asset: to, from_amount: amount, destination } }
}







// -----------------------------------------------------------
// defaultHandlers
// -----------------------------------------------------------
//
// In the order of routes.py: the rates, the reserves, the
// order list, a new order and one order. Every answer is a
// fresh copy, so a page that edits what it got cannot leak
// into the next test.
//
// Used by:
//   - server.js
// -----------------------------------------------------------

export const defaultHandlers = [

  // Live rates + the amount limits the backend enforces
  http.get(abs('/api/exchange/rates'), () => HttpResponse.json(structuredClone(f.rates))),

  // Every chain's reserve wallet with its balance
  http.get(abs('/api/exchange/reserves'), () => HttpResponse.json(f.reserves())),

  // The latest orders, newest first
  http.get(abs('/api/exchange/orders'), ({ request }) => HttpResponse.json(f.orders().slice(0, listLimit(request)))),

  // A new order — a body that is not a JSON object counts as
  // an empty one, as get_json(silent=True) or {} makes it, and
  // a JSON list is the crash routes.py turns into its 500
  http.post(abs('/api/exchange/orders'), async ({ request }) => {
    let payload
    try { payload = (await request.json()) || {} } catch { payload = {} }
    if (typeof payload !== 'object' || Array.isArray(payload)) return refuse(f.CREATE_FAILURE, 500)

    const verdict = refusalOf(payload)
    if (verdict.accepted) return HttpResponse.json(f.createdOrder(verdict.accepted), { status: 201 })
    return refuse(verdict.message, verdict.status)
  }),

  // One order by id
  http.get(abs('/api/exchange/orders/:orderId'), ({ params }) => {
    const found = f.orderById(params.orderId)
    return found ? HttpResponse.json(found) : refuse('Not found', 404)
  }),
]
