// -----------------------------------------------------------
//  [*] Reserves — the payout wallets page (/reserves)
//
//  Operator view of the exchange's reserve (payout) wallets:
//  one card per chain with the reserve address, its live
//  on-chain balance and what it can still pay out to a new
//  order (the balance less what it owes the orders in
//  progress), polled from /api/exchange/reserves so an
//  operator can see directly on the GUI which wallet needs a
//  top-up — the exchange refuses the orders a reserve cannot
//  cover.
//
//  A chain whose Electrum server is down or still syncing
//  reports an error for its balance — the card still shows
//  the address (derived locally by the backend) so it can be
//  topped up anyway.
//
//  Split into (root component last):
//
//    formatAmount   — a coin amount for display
//    BalanceReadout — big confirmed number, pending and
//                     available lines
//    ReserveCard    — one chain's wallet card
//    Reserves       — the page (default export)
// -----------------------------------------------------------

import { useEffect, useState } from 'react'

import { ExchangeApi } from '../Exchange/lib/api.js'
import Layout from '../Exchange/components/Layout.jsx'
import CoinIcon from '../Exchange/components/CoinIcon.jsx'
import CopyableAddress from '../Exchange/components/CopyableAddress.jsx'


// How often the balances are read again — the page says so
// under its title
const POLL_INTERVAL_MS = 10000







// -----------------------------------------------------------
// formatAmount
// -----------------------------------------------------------
//
// A coin amount for display: up to 8 decimals in the
// runtime's locale, no trailing noise, and nothing at all for
// a value that is not a number.
//
// Used by:
//   - BalanceReadout (below)
// -----------------------------------------------------------

const formatAmount = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  return n.toLocaleString(undefined, { maximumFractionDigits: 8 })
}







// -----------------------------------------------------------
// BalanceReadout
// -----------------------------------------------------------
//
// The card's main number: the confirmed balance in big type,
// with an extra "pending" line whenever unconfirmed coins are
// on the way, and what is available for new orders. With
// nothing available — an empty reserve, or one owed all it
// holds — it warns that orders paying out on this chain are
// refused until it is topped up. When the backend could not
// reach Electrum it shows the error instead.
//
// Used by:
//   - ReserveCard (below)
// -----------------------------------------------------------

function BalanceReadout({ reserve }) {

  if (reserve.error) {
    return (
      <div className="rounded-xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-[13px] font-semibold text-amber-300">
        Balance unavailable: {reserve.error}
      </div>
    )
  }


  // Nothing to spare for a new order: what it holds, if anything, is
  // owed to the orders in progress (an answer from before the backend
  // told it apart counts an empty balance alone)
  const hasNothingToSpare = typeof reserve.available === 'number' ? reserve.available === 0 : reserve.confirmed === 0


  return (
    <div>
      <div className={`text-3xl font-extrabold tabular-nums ${hasNothingToSpare ? 'text-amber-300' : 'text-white'}`}>
        {formatAmount(reserve.confirmed)}
        <span className="ml-2 text-base font-bold text-white/50">{reserve.shortName}</span>
      </div>

      {reserve.unconfirmed !== 0 && (
        <div className="mt-1 text-sm text-white/55">
          {formatAmount(reserve.unconfirmed)} {reserve.shortName} pending confirmation
        </div>
      )}

      {typeof reserve.available === 'number' && (
        <div className="mt-1 text-sm text-white/55">
          {formatAmount(reserve.available)} {reserve.shortName} available for new orders
        </div>
      )}

      {hasNothingToSpare && (
        <div className="mt-1 text-sm font-semibold text-amber-300">
          Nothing to spare — orders paying out on this chain are refused until it is topped up.
        </div>
      )}
    </div>
  )
}







// -----------------------------------------------------------
// ReserveCard
// -----------------------------------------------------------
//
// One chain's reserve wallet: the coin's logo + name, the
// balance readout, the copyable address to send the top-up
// to, and a link to the chain's block explorer.
//
// Used by:
//   - Reserves (below) — one per chain
// -----------------------------------------------------------

function ReserveCard({ reserve }) {
  return (
    <div className="grid content-start gap-4 rounded-2xl border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl">

      {/* Chain name */}
      <div className="flex items-center gap-3">
        <CoinIcon asset={reserve.asset} icon={reserve.icon} size={38} />
        <div>
          <div className="text-lg font-extrabold text-white">{reserve.fullName}</div>
          <div className="text-xs font-bold uppercase tracking-widest text-white/50">
            Reserve wallet · {reserve.shortName}
          </div>
        </div>
      </div>

      {/* Balance */}
      <BalanceReadout reserve={reserve} />

      <hr className="border-white/[0.08]" />

      {/* Top-up address */}
      <div>
        <div className="mb-2 text-sm font-semibold">Top-up address:</div>
        <CopyableAddress value={reserve.address} />
      </div>

      {reserve.blockExplorer && (
        <a
          href={reserve.blockExplorer}
          target="_blank"
          rel="noreferrer"
          className="text-sm font-semibold text-indigo-300 transition-colors hover:text-indigo-200"
        >
          View on block explorer →
        </a>
      )}
    </div>
  )
}







// -----------------------------------------------------------
// Reserves (default export)
// -----------------------------------------------------------
//
// The page component: polls the reserves endpoint every
// POLL_INTERVAL_MS and renders one card per chain. Until the
// first answer it says it is loading; a failed refresh keeps
// the cards on screen under an error banner, which the next
// refresh that gets through clears.
//
// Used by:
//   - App.jsx — route /reserves
// -----------------------------------------------------------

export default function Reserves() {

  const [reserves, setReserves] = useState(null)
  const [error, setError] = useState(null)


  // Poll the reserves until the component unmounts
  useEffect(() => {
    let stop = false

    const load = async () => {
      try {
        const remote = await ExchangeApi.getReserves()
        if (stop) return
        setReserves(remote)
        setError(null)
      } catch (err) {
        if (stop) return
        setError(err.message || 'Failed to load reserves')
      }
    }

    load()
    const interval = setInterval(load, POLL_INTERVAL_MS)
    return () => { stop = true; clearInterval(interval) }
  }, [])


  return (
    <Layout>
      <div className="mx-auto max-w-[880px]">

        {/* Page title */}
        <div className="mb-7 text-center">
          <h1 className="text-3xl font-extrabold tracking-tight text-white">
            Exchange <span className="bg-gradient-to-r from-indigo-300 to-cyan-300 bg-clip-text text-transparent">reserves</span>
          </h1>
          <p className="mt-1.5 text-sm text-white/55">
            Payouts are funded from these wallets — top up whichever runs low.
            Balances refresh every {POLL_INTERVAL_MS / 1000} seconds.
          </p>
        </div>


        {/* Error / loading / cards */}
        {error && (
          <div className="mb-4 rounded-xl border border-red-400/30 bg-red-500/10 px-4 py-3 text-sm font-semibold text-red-300">
            {error}
          </div>
        )}

        {!reserves && !error && (
          <div className="grid place-items-center py-20">
            <span className="h-8 w-8 animate-spin rounded-full border-[3px] border-indigo-300/30 border-t-indigo-300" />
            <p className="mt-4 text-white/60">Loading reserves...</p>
          </div>
        )}

        {reserves && (
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            {/* Keyed by the network — by position for entries that came without one */}
            {reserves.map((reserve, index) => (
              <ReserveCard key={reserve.network ?? index} reserve={reserve} />
            ))}
          </div>
        )}
      </div>
    </Layout>
  )
}
