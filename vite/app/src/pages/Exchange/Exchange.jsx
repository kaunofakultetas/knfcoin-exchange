// -----------------------------------------------------------
//  [*] Exchange — the swap page (/exchange)
//
//  The swap form: pick a direction (KNF Coin <-> LTC Testnet),
//  enter an amount and the address to receive on. On submit it
//  creates an order on the backend and navigates to that
//  order's status page. The final rate is always locked in
//  when the deposit confirms.
//
//  Rates and amount limits come live from the backend
//  (/api/exchange/rates) so the quote the student sees matches
//  what the server will actually enforce — the most an order
//  can be for capped at what the exchange can pay out right
//  now, the way the backend refuses one it cannot cover. There
//  is deliberately no offline fallback: if the API is down the
//  student sees the real error.
//
//  Split into (root component last):
//
//    formatAmount     — a coin amount for display
//    timeAgo          — how long ago a moment was, in words
//    useLiveRates     — polls /rates so quotes stay current
//    useRecentOrders  — loads the order list once
//    useNow           — the current time, renewed on a beat
//    mostPayable      — the most an order can be for, by what
//                       the exchange can pay out
//    SwapPanel        — one "You send" / "You receive" box
//    FlipButton       — swaps the trade direction
//    SwapForm         — form state, validation and submit
//    OrderAge         — how long ago an order was made
//    RecentOrders     — list of the latest orders, or why it
//                       is not there
//    Exchange         — the page (default export)
// -----------------------------------------------------------

import { useMemo, useState, useEffect } from 'react'
import { useNavigate, Link } from 'react-router-dom'

import { ExchangeApi } from './lib/api.js'
import { hasReceivedCoins, sendsCoinsBack, shownStatus } from './lib/orders.js'
import Layout from './components/Layout.jsx'
import CoinIcon from './components/CoinIcon.jsx'
import StatusBadge from './components/StatusBadge.jsx'


// Asset labels — MUST match ASSET_TO_NETWORK in the backend:
// KNF Coin...
const KNF = 'KNF Coin'
// ...and Litecoin Testnet4, labelled LTC Testnet
const LTCT = 'LTC Testnet'

// Ticker-style short names for compact UI spots (hints, rate line).
const SYMBOLS = { [KNF]: 'KNF', [LTCT]: 'tLTC4' }

// The units an order's age is told in, the largest first, each
// with its length in milliseconds (a month taken as 30 days)
const AGE_UNITS = [
  ['year', 365 * 24 * 60 * 60 * 1000],
  ['month', 30 * 24 * 60 * 60 * 1000],
  ['week', 7 * 24 * 60 * 60 * 1000],
  ['day', 24 * 60 * 60 * 1000],
  ['hour', 60 * 60 * 1000],
  ['minute', 60 * 1000],
]

// How the English UI words a time in the past — always with its
// number, never a calendar word that could misplace it
const RELATIVE_TIME = new Intl.RelativeTimeFormat('en', { numeric: 'always' })

// How often the ages in the order list are worded anew
const AGE_REFRESH_MS = 30 * 1000

// Satoshis per coin: the most an order can be for is rounded
// down to one
const COIN = 1e8







// -----------------------------------------------------------
// formatAmount
// -----------------------------------------------------------
//
// A coin amount for display: trailing noise trimmed, at most
// 8 decimals in the runtime's locale, and nothing at all for
// a value that is not a finite number.
//
// Used by:
//   - SwapForm, RecentOrders (below)
// -----------------------------------------------------------

const formatAmount = (value) => {
  if (!Number.isFinite(value)) return ''
  return value.toLocaleString(undefined, { maximumFractionDigits: 8 })
}







// -----------------------------------------------------------
// timeAgo
// -----------------------------------------------------------
//
// How long before `now` a moment was, in words: in the
// largest unit it spans at least once — minutes up to years,
// rounded down — and "just now" for less than a minute, or
// for a moment that the browser's clock still has ahead of
// it.
//
// Used by:
//   - OrderAge (below)
// -----------------------------------------------------------

function timeAgo(moment, now) {
  const elapsed = now - moment
  for (const [unit, length] of AGE_UNITS) {
    if (elapsed >= length) return RELATIVE_TIME.format(-Math.floor(elapsed / length), unit)
  }
  return 'just now'
}







// -----------------------------------------------------------
// useLiveRates
// -----------------------------------------------------------
//
// Loads the rates and the amount limits from the backend,
// then keeps polling every 15 seconds so a long-lived tab
// stays current; a failed poll keeps the last answer. Returns
// null until the first answer arrives (or while the API is
// down), which the form renders as "Rate unavailable".
//
// Used by:
//   - Exchange (below)
// -----------------------------------------------------------

function useLiveRates() {

  const [rates, setRates] = useState(null)


  useEffect(() => {
    let stop = false

    const load = async () => {
      try {
        const snapshot = await ExchangeApi.getRates()
        if (!stop) setRates(snapshot)
      } catch {
        // Leave rates null; the quote box shows a "rate unavailable" hint.
      }
    }

    load()
    const interval = setInterval(load, 15000)
    return () => { stop = true; clearInterval(interval) }
  }, [])


  return rates
}







// -----------------------------------------------------------
// useRecentOrders
// -----------------------------------------------------------
//
// The student's latest orders for the list at the bottom of
// the page. Loaded once per visit — the individual order
// pages do their own live polling. Returns the orders (null
// until they arrive) and, when they could not be read, the
// reason, so a failure is never mistaken for an empty list.
//
// Used by:
//   - Exchange (below)
// -----------------------------------------------------------

function useRecentOrders(limit = 5) {

  const [recent, setRecent] = useState({ orders: null, error: null })


  useEffect(() => {
    let stop = false

    const load = async () => {
      try {
        const remote = await ExchangeApi.listOrders(limit)
        if (!stop) setRecent({ orders: remote, error: null })
      } catch (err) {
        if (!stop) setRecent({ orders: null, error: err.message || 'Failed to load orders' })
      }
    }

    load()
    return () => { stop = true }
  }, [limit])


  return recent
}







// -----------------------------------------------------------
// useNow
// -----------------------------------------------------------
//
// The current time in epoch milliseconds, renewed every
// intervalMs — so whatever is worded from it (how long ago an
// order was made) keeps up while the page stays open. It asks
// the backend nothing.
//
// Used by:
//   - RecentOrders (below)
// -----------------------------------------------------------

function useNow(intervalMs) {

  const [now, setNow] = useState(() => Date.now())


  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), intervalMs)
    return () => clearInterval(timer)
  }, [intervalMs])


  return now
}







// -----------------------------------------------------------
// mostPayable
// -----------------------------------------------------------
//
// The most an order paying in one asset can be for, given
// what the exchange can still pay out of the other (the
// rates' capacity, in whole coins) and the rate between them
// — rounded down to the satoshi, as the backend rounds the
// most it offers. Nothing when either is not known; the
// backend still checks the order itself.
//
// Used by:
//   - SwapForm (below) — the hint and the check before submit
// -----------------------------------------------------------

function mostPayable(capacity, rate) {
  if (!Number.isFinite(capacity) || !Number.isFinite(rate) || rate <= 0) return null
  return Math.floor((capacity * COIN) / rate) / COIN
}







// -----------------------------------------------------------
// SwapPanel
// -----------------------------------------------------------
//
// One half of the swap widget: the "You send" panel holds an
// editable amount input, the "You receive" panel a read-only
// estimate. The asset chip — the coin's logo and name — and
// the hint line under the amount are provided by the parent.
//
// Used by:
//   - SwapForm (below) — twice, around the flip button
// -----------------------------------------------------------

function SwapPanel({ label, asset, icon, value, onChange, readOnly, hint }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.045] p-5 backdrop-blur-xl transition-colors focus-within:border-indigo-400/50">

      {/* Label + asset chip */}
      <div className="flex items-center justify-between gap-3">
        <span className="text-xs font-bold uppercase tracking-widest text-white/50">{label}</span>
        <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-black/25 py-1.5 pl-1.5 pr-3.5 text-sm font-bold">
          <CoinIcon asset={asset} icon={icon} size={24} />
          {asset}
        </span>
      </div>

      {/* Amount */}
      <input
        className="mt-3 w-full border-0 bg-transparent text-3xl font-bold tracking-tight outline-none placeholder:text-white/25"
        inputMode="decimal"
        placeholder="0.00000000"
        value={value}
        readOnly={readOnly}
        onChange={readOnly ? undefined : (e) => onChange(e.target.value)}
      />

      {/* Limits / rate hint */}
      <div className="mt-2 text-xs text-white/50">{hint}</div>
    </div>
  )
}







// -----------------------------------------------------------
// FlipButton
// -----------------------------------------------------------
//
// The round arrow between the two panels that swaps the trade
// direction. Sits horizontally on desktop (⇄) and vertically
// in the stacked mobile layout (⇅).
//
// Used by:
//   - SwapForm (below)
// -----------------------------------------------------------

function FlipButton({ onFlip }) {
  return (
    <div className="z-10 -my-4 flex items-center justify-center md:my-0 md:-mx-1">
      <button
        type="button"
        onClick={onFlip}
        aria-label="Swap direction"
        className="grid h-11 w-11 place-items-center rounded-full border border-white/15 bg-[#181b36] text-lg text-indigo-300 shadow-lg transition-all hover:rotate-180 hover:border-indigo-400/60 hover:text-white"
        style={{ transitionDuration: '300ms' }}
      >
        <span className="hidden md:inline">⇄</span>
        <span className="md:hidden">⇅</span>
      </button>
    </div>
  )
}







// -----------------------------------------------------------
// SwapForm
// -----------------------------------------------------------
//
// Owns everything about creating an order: the form state
// (direction, amount, destination), the live quote derived
// from the rates snapshot, cheap client-side validation —
// the limits, and the most the exchange can pay out right now
// (it cannot pay out at all when that is below the smallest
// order) — and the submit that navigates to the new order's
// page.
//
// The backend re-validates everything and prices the order
// itself, so submit only sends the intent — never the
// computed to_amount or rate.
//
// Used by:
//   - Exchange (below)
// -----------------------------------------------------------

function SwapForm({ rates }) {

  const [fromAsset, setFromAsset] = useState(KNF)
  const [toAsset, setToAsset] = useState(LTCT)
  const [fromAmount, setFromAmount] = useState('')
  const [destination, setDestination] = useState('')

  const [formError, setFormError] = useState('')
  const [submitting, setSubmitting] = useState(false)

  const navigate = useNavigate()


  // The live quote: the rate and the limits of the chosen
  // direction, and the estimate they give the amount typed
  const rate = rates?.pairs?.[`${fromAsset}->${toAsset}`] ?? null
  const limits = rates?.limits?.[fromAsset] ?? null

  // The most the exchange can take in this direction right now: what
  // it can pay out, within the limits; none at all below the smallest
  // order
  const payable = mostPayable(rates?.capacity?.[toAsset], rate)
  const cannotPayOut = payable != null && limits != null && payable < limits.min
  const most = limits && payable != null ? Math.min(limits.max, payable) : limits?.max

  const toAmount = useMemo(() => {
    const amount = Number(fromAmount)
    if (!Number.isFinite(amount) || amount <= 0 || rate == null) return ''
    return formatAmount(amount * rate)
  }, [fromAmount, rate])


  // A flipped direction starts the amount over: it was typed
  // in the other coin
  const handleFlip = () => {
    setFromAsset(toAsset)
    setToAsset(fromAsset)
    setFromAmount('')
    setFormError('')
  }


  // Sends only the intent — the backend validates it again and
  // prices the order itself — then opens the new order's page
  const handleSubmit = async (e) => {
    e.preventDefault()
    setFormError('')

    // Cheap client-side checks first, so obvious mistakes never hit the API.
    const amount = Number(fromAmount)
    if (!Number.isFinite(amount) || amount <= 0) {
      setFormError('Enter a valid amount')
      return
    }
    if (limits && (amount < limits.min || amount > limits.max)) {
      setFormError(`Amount must be between ${limits.min} and ${limits.max} ${fromAsset}`)
      return
    }
    if (cannotPayOut) {
      setFormError(`The exchange cannot pay out ${toAsset} right now - please try again later`)
      return
    }
    if (payable != null && amount > payable) {
      setFormError(`The exchange can take at most ${payable} ${fromAsset} right now`)
      return
    }
    if (!destination.trim()) {
      setFormError(`Enter your ${toAsset} address`)
      return
    }

    setSubmitting(true)
    try {
      const created = await ExchangeApi.createOrder({
        from_asset:  fromAsset,
        to_asset:    toAsset,
        from_amount: amount,
        destination: destination.trim(),
      })
      navigate(`/exchange/order/${created.id}`)
    } catch (err) {
      setFormError(err.message || 'Could not create the order')
      setSubmitting(false)
    }
  }


  return (
    <form onSubmit={handleSubmit} className="grid gap-3">

      {/* Send / receive panels, side by side on desktop with the flip
          button between them (stacked vertically on mobile) */}
      <div className="grid grid-cols-1 items-stretch gap-2 md:grid-cols-[1fr_auto_1fr]">
        <SwapPanel
          label="You send"
          asset={fromAsset}
          icon={rates?.icons?.[fromAsset]}
          value={fromAmount}
          onChange={setFromAmount}
          hint={
            !limits ? 'Loading limits...'
              : cannotPayOut ? `The exchange cannot pay out ${SYMBOLS[toAsset]} right now`
                : `Min ${limits.min} · Max ${most} ${SYMBOLS[fromAsset]}`
          }
        />

        <FlipButton onFlip={handleFlip} />

        <SwapPanel
          label="You receive"
          asset={toAsset}
          icon={rates?.icons?.[toAsset]}
          value={toAmount}
          readOnly
          hint={
            rate != null
              ? (
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-400" />
                  1 {SYMBOLS[fromAsset]} ≈ {formatAmount(rate)} {SYMBOLS[toAsset]}
                </span>
              )
              : 'Rate unavailable'
          }
        />
      </div>


      {/* Destination address */}
      <input
        className="w-full rounded-xl border border-white/[0.14] bg-black/25 px-4 py-3.5 font-mono text-sm outline-none transition-all placeholder:font-sans placeholder:text-white/35 focus:border-indigo-400/60 focus:ring-2 focus:ring-indigo-500/20"
        placeholder={`Your ${toAsset} address (${toAsset === KNF ? 'knf1...' : 'tltc1...'})`}
        value={destination}
        onChange={(e) => setDestination(e.target.value)}
      />


      {/* Error banner */}
      {formError && (
        <div className="rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm font-semibold text-red-300">
          {formError}
        </div>
      )}


      {/* Submit */}
      <button
        type="submit"
        disabled={submitting}
        className="mx-auto mt-1 inline-flex w-full max-w-md items-center justify-center gap-2.5 rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-600 px-6 py-4 text-base font-bold text-white shadow-lg shadow-indigo-500/30 transition-all hover:brightness-110 active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50 disabled:hover:brightness-100"
      >
        {submitting && <span className="h-4 w-4 animate-spin rounded-full border-2 border-white/30 border-t-white" />}
        {submitting ? 'Creating order...' : 'Exchange now'}
      </button>

    </form>
  )
}







// -----------------------------------------------------------
// OrderAge
// -----------------------------------------------------------
//
// How long ago an order was made, in words, after a dot
// separating it from the order's id; the exact moment is the
// time element's datetime and shows on hover. Nothing at all
// for a creation time the answer did not carry as a number.
//
// Used by:
//   - RecentOrders (below) — one per row
// -----------------------------------------------------------

function OrderAge({ createdAt, now }) {

  if (typeof createdAt !== 'number') return null
  const created = new Date(createdAt)
  if (Number.isNaN(created.getTime())) return null


  return (
    <>
      <span aria-hidden="true">·</span>
      <time dateTime={created.toISOString()} title={created.toLocaleString()}>{timeAgo(createdAt, now)}</time>
    </>
  )
}







// -----------------------------------------------------------
// RecentOrders
// -----------------------------------------------------------
//
// The student's latest orders as clickable rows leading to
// each order's status page, each telling how long ago it was
// made — worded anew every AGE_REFRESH_MS — and wearing the
// status the pages show it with: done as soon as its payout
// is out. Until the list
// arrives it says it is loading; when it could not be read it
// says so, with the reason — "No orders yet" is kept for a
// list that really is empty.
//
// Used by:
//   - Exchange (below)
// -----------------------------------------------------------

function RecentOrders({ orders, error }) {

  // Before the early returns: a hook runs on every render
  const now = useNow(AGE_REFRESH_MS)


  if (error) {
    return <p className="text-sm text-red-300">{`Could not load your recent orders: ${error}`}</p>
  }

  if (!orders) {
    return <p className="text-sm text-white/50">Loading orders...</p>
  }

  if (orders.length === 0) {
    return <p className="text-sm text-white/50">No orders yet — your swaps will appear here.</p>
  }


  // Once coins have arrived the row shows what was ACTUALLY deposited
  // (the payout scales with it), not the amount agreed at creation. The
  // receive side matches: exact once the backend locked the rate,
  // estimated from the deposit before that — and an order that did not
  // go through says its coins go back instead.
  const sentAmount = (order) =>
    hasReceivedCoins(order) ? order.receivedAmount : order.fromAmount

  const receiveAmount = (order) =>
    order.lockedRate != null ? order.toAmount : sentAmount(order) * order.rate


  return (
    <div className="grid gap-2.5">
      {/* Keyed by the order id — by position for rows that came without one */}
      {orders.map((order, index) => (
        <Link
          key={order.id ?? index}
          to={`/exchange/order/${order.id}`}
          className="group grid grid-cols-[auto_1fr_auto] items-center gap-4 rounded-2xl border border-white/10 bg-white/[0.045] p-4 backdrop-blur-xl transition-all hover:border-indigo-400/40 hover:bg-white/[0.07]"
        >
          {/* Overlapping coin icons showing the direction */}
          <span className="flex items-center">
            <CoinIcon asset={order.fromAsset} icon={order.fromIcon} size={30} />
            <span className="-ml-2.5 rounded-full ring-2 ring-[#0b0d1d]">
              <CoinIcon asset={order.toAsset} icon={order.toIcon} size={30} />
            </span>
          </span>

          <span className="min-w-0">
            <span className="block truncate text-sm font-bold">
              {formatAmount(sentAmount(order))} {order.fromAsset}
              <span className="mx-1.5 text-white/40">→</span>
              {sendsCoinsBack(order) ? 'sent back' : `≈${formatAmount(receiveAmount(order))} ${order.toAsset}`}
            </span>
            <span className="mt-0.5 flex flex-wrap items-baseline gap-x-1.5 text-xs text-white/45">
              <span className="font-mono">#{order.id}</span>
              <OrderAge createdAt={order.createdAt} now={now} />
            </span>
          </span>

          <StatusBadge status={shownStatus(order)} />
        </Link>
      ))}
    </div>
  )
}







// -----------------------------------------------------------
// Exchange (default export)
// -----------------------------------------------------------
//
// The page itself, just composition: load the live data
// through the two hooks and lay out title, form and order
// list. All form logic lives in SwapForm.
//
// Used by:
//   - App.jsx — route /exchange
// -----------------------------------------------------------

export default function Exchange() {

  const rates = useLiveRates()
  const recentOrders = useRecentOrders(5)


  return (
    <Layout>
      <div className="mx-auto max-w-[960px]">

        {/* Page title */}
        <div className="mb-7 text-center">
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Swap <span className="bg-gradient-to-r from-indigo-300 to-cyan-300 bg-clip-text text-transparent">testnet coins</span>
          </h1>
          <p className="mt-1.5 text-sm text-white/55">
            Exchange KNF Coin and Litecoin Testnet4 — settled fully on-chain.
          </p>
        </div>


        <SwapForm rates={rates} />


        {/* Recent orders */}
        <section className="mt-10">
          <h2 className="mb-3 text-lg font-bold text-white">Recent orders</h2>
          <RecentOrders orders={recentOrders.orders} error={recentOrders.error} />
        </section>
      </div>
    </Layout>
  )
}
