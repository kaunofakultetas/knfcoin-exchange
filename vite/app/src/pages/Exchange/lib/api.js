// -----------------------------------------------------------
//  [*] ExchangeApi — the backend's REST API, as the pages call it
//
//  Thin wrapper around the backend REST API mounted at
//  /api/exchange/* (proxied to the Flask service by Caddy).
//
//  Two things worth knowing:
//    - the backend speaks snake_case; camelizeOrder converts
//      an order row into the camelCase shape the React pages
//      use (its refunds through camelizeRefund and
//      camelizeRecipient), camelizeReserve a reserve wallet
//      entry
//    - every non-2xx answer becomes an Error carrying the
//      backend's own sentence, so callers can show it verbatim
//      instead of a generic failure
// -----------------------------------------------------------







// -----------------------------------------------------------
// ExchangeApi
// -----------------------------------------------------------
//
// One method per call the pages make, each a promise of the
// answer's parsed body — the rates (with each coin's logo URL)
// as the backend sends them, an order or a list of them and
// the reserves camelized — or a rejection whose message is
// the backend's sentence.
//
// Used by:
//   - pages/Home/Home.jsx — LiveRateChip
//   - pages/Exchange/Exchange.jsx — useLiveRates,
//     useRecentOrders, SwapForm
//   - pages/Exchange/Order.jsx — the order poll
//   - pages/Reserves/Reserves.jsx — the reserves poll
// -----------------------------------------------------------

export const ExchangeApi = {

  // Live rates + the amount limits the backend enforces.
  getRates() {
    return http('GET', '/api/exchange/rates')
  },

  // Reserve (payout) wallet of every chain with its live balance.
  getReserves() {
    return http('GET', '/api/exchange/reserves')
      .then((rows) => rows.map(camelizeReserve))
  },

  createOrder(payload) {
    return http('POST', '/api/exchange/orders', payload).then(camelizeOrder)
  },

  listOrders(limit = 20) {
    return http('GET', `/api/exchange/orders?limit=${encodeURIComponent(limit)}`)
      .then((rows) => rows.map(camelizeOrder))
  },

  getOrder(orderId) {
    return http('GET', `/api/exchange/orders/${encodeURIComponent(orderId)}`).then(camelizeOrder)
  },
}







// -----------------------------------------------------------
// http
// -----------------------------------------------------------
//
// fetch + JSON + error unwrapping: the body goes out as JSON
// and a 2xx answer comes back parsed. Anything else throws an
// Error carrying the backend's { error } sentence, or the
// status-code message when the answer has none.
//
// Used by:
//   - ExchangeApi (above) — every method
// -----------------------------------------------------------

async function http(method, path, body) {

  const res = await fetch(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })


  if (!res.ok) {
    // Prefer the backend's { error } message; fall back to the status code.
    let message = `Request failed (${res.status})`
    try {
      const data = await res.json()
      if (data?.error) message = data.error
    } catch {
      // response had no JSON body — keep the status-code message
    }
    throw new Error(message)
  }


  return res.json()
}







// -----------------------------------------------------------
// camelizeOrder
// -----------------------------------------------------------
//
// An order row as the backend sends it, in the camelCase
// shape the pages read — only the columns they use, the logo
// URLs of its two coins and its refunds, always a list (of
// the entries that are objects at all); a missing row passes
// through as it came.
//
// Used by:
//   - ExchangeApi (above) — createOrder, listOrders, getOrder
// -----------------------------------------------------------

function camelizeOrder(o) {
  if (!o) return o

  return {
    id:                o.id,
    pair:              o.pair,
    fromAsset:         o.from_asset,
    toAsset:           o.to_asset,
    fromAmount:        o.from_amount,
    toAmount:          o.to_amount,
    rate:              o.rate,
    lockedRate:        o.locked_rate,
    destination:       o.destination,
    status:            o.status,
    confirmTarget:     o.confirm_target,
    confirmCount:      o.confirm_count,
    depositAddress:    o.deposit_address,
    depositScripthash: o.deposit_scripthash,
    receivedAmount:    o.received_amount,
    txDepositId:       o.tx_deposit_id,
    txSendId:          o.tx_send_id,
    error:             o.error,
    fromIcon:          o.from_icon,
    toIcon:            o.to_icon,
    refunds:           objectsIn(o.refunds).map(camelizeRefund),
    createdAt:         o.created_at,
    updatedAt:         o.updated_at,
    expiresAt:         o.expires_at,
  }
}







// -----------------------------------------------------------
// camelizeRefund
// -----------------------------------------------------------
//
// One refund of an order, as the order page lists it: its
// txid, whether it has confirmed, when it was made, and the
// senders it pays back, always a list.
//
// Used by:
//   - camelizeOrder (above)
// -----------------------------------------------------------

function camelizeRefund(refund) {
  return {
    txid:       refund.txid,
    confirmed:  refund.confirmed === true,
    createdAt:  refund.created_at,
    recipients: objectsIn(refund.recipients).map(camelizeRecipient),
  }
}







// -----------------------------------------------------------
// camelizeRecipient
// -----------------------------------------------------------
//
// One sender a refund pays back: the address, null for one
// the exchange cannot name, and the amount in whole coins.
//
// Used by:
//   - camelizeRefund (above)
// -----------------------------------------------------------

function camelizeRecipient(recipient) {
  return {
    address: recipient.address,
    amount:  recipient.amount,
  }
}







// -----------------------------------------------------------
// objectsIn
// -----------------------------------------------------------
//
// The entries of a list that are objects, or nothing at all
// for a value that is not a list — so a page never trips over
// a refund that came broken.
//
// Used by:
//   - camelizeOrder, camelizeRefund (above)
// -----------------------------------------------------------

function objectsIn(list) {
  return Array.isArray(list) ? list.filter((entry) => entry !== null && typeof entry === 'object') : []
}







// -----------------------------------------------------------
// camelizeReserve
// -----------------------------------------------------------
//
// One reserve wallet entry, in the camelCase shape the
// reserves page reads — available being what it can still pay
// out to a new order.
//
// Used by:
//   - ExchangeApi (above) — getReserves
// -----------------------------------------------------------

function camelizeReserve(r) {
  return {
    network:       r.network,
    asset:         r.asset,
    shortName:     r.short_name,
    fullName:      r.full_name,
    blockExplorer: r.block_explorer,
    icon:          r.icon,
    address:       r.address,
    confirmed:     r.confirmed,
    unconfirmed:   r.unconfirmed,
    available:     r.available,
    error:         r.error,
  }
}
