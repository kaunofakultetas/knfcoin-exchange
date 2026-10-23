// -----------------------------------------------------------
//  [*] Home — the landing page (/)
//
//  The entry hub students land on:
//
//    - hero section — what the playground is, with the live
//      KNF -> tLTC4 rate pulled from /api/exchange/rates
//    - tool cards   — the two tools in the playground: the
//      KNF <-> tLTC4 swap at /exchange, and the block
//      explorer at /explorer/ (served by Caddy, not React
//      Router, so its card is a plain link)
//    - a short "how it works" strip explaining the swap flow
//
//  It reuses the shared Layout so the header, footer and
//  background match the rest of the app.
//
//  Split into (root component last):
//
//    LiveRateChip   — the live rate under the hero
//    ToolCard       — one card per playground tool
//    HowItWorksStep — one numbered step of the strip
//    Home           — the page (default export)
// -----------------------------------------------------------

import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { ExchangeApi } from '../Exchange/lib/api.js'
import Layout from '../Exchange/components/Layout.jsx'







// -----------------------------------------------------------
// LiveRateChip
// -----------------------------------------------------------
//
// Small pill under the hero showing the current KNF -> tLTC4
// rate with a pulsing "live" dot. Shows nothing at all until
// the rates endpoint answers, so the hero never displays a
// broken placeholder.
//
// Used by:
//   - Home (below)
// -----------------------------------------------------------

function LiveRateChip() {

  const [rate, setRate] = useState(null)


  useEffect(() => {
    let stop = false

    ExchangeApi.getRates()
      .then((snapshot) => {
        if (!stop) setRate(snapshot?.pairs?.['KNF Coin->LTC Testnet'] ?? null)
      })
      .catch(() => {
        // Rates unavailable — simply render nothing.
      })

    return () => { stop = true }
  }, [])


  if (rate == null) return null

  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-sm font-semibold backdrop-blur-md">
      <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
      1 KNF ≈ {rate.toLocaleString(undefined, { maximumFractionDigits: 8 })} tLTC4
    </span>
  )
}







// -----------------------------------------------------------
// ToolCard
// -----------------------------------------------------------
//
// One big card per playground tool: an in-app router link
// when given `to`, a plain link for a destination outside
// React Router (the explorer at /explorer/).
//
// Used by:
//   - Home (below) — one per tool
// -----------------------------------------------------------

function ToolCard({ to, href, icon, title, description }) {

  const className =
    'group block rounded-2xl border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl ' +
    'shadow-[0_18px_50px_rgba(0,0,0,0.35)] transition-all duration-200 ' +
    'hover:-translate-y-0.5 hover:border-indigo-400/50 hover:bg-white/[0.07]'


  const content = (
    <>
      <div className="mb-4 grid h-12 w-12 place-items-center rounded-xl bg-gradient-to-br from-indigo-500/30 to-cyan-500/20 text-2xl ring-1 ring-white/10">
        {icon}
      </div>

      <div className="flex items-center gap-2 text-lg font-extrabold text-white">
        {title}
        <span className="translate-x-0 text-indigo-300 transition-transform duration-200 group-hover:translate-x-1">→</span>
      </div>

      <p className="mt-1.5 text-sm leading-relaxed text-white/60">{description}</p>
    </>
  )


  if (href) {
    return <a href={href} className={className}>{content}</a>
  }

  return <Link to={to} className={className}>{content}</Link>
}







// -----------------------------------------------------------
// HowItWorksStep
// -----------------------------------------------------------
//
// One numbered step in the "how a swap works" strip.
//
// Used by:
//   - Home (below)
// -----------------------------------------------------------

function HowItWorksStep({ number, title, description }) {
  return (
    <div className="flex gap-3.5">
      <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-indigo-500/20 text-sm font-bold text-indigo-300 ring-1 ring-indigo-400/30">
        {number}
      </span>
      <div>
        <div className="font-bold text-white">{title}</div>
        <p className="mt-0.5 text-sm text-white/60">{description}</p>
      </div>
    </div>
  )
}







// -----------------------------------------------------------
// Home (default export)
// -----------------------------------------------------------
//
// Page component assembling the sections: hero + live rate,
// the two tool cards and the how-it-works strip.
//
// Used by:
//   - App.jsx — route /
// -----------------------------------------------------------

export default function Home() {
  return (
    <Layout>
      <div className="mx-auto max-w-[980px]">

        {/* Hero */}
        <section className="pt-8 pb-4 text-center md:pt-14">
          <span className="mb-5 inline-block rounded-full border border-amber-400/30 bg-amber-400/10 px-3.5 py-1.5 text-xs font-bold uppercase tracking-widest text-amber-300">
            Testnet playground
          </span>

          <h1 className="text-4xl font-extrabold leading-tight tracking-tight text-white md:text-5xl">
            Learn crypto by
            <span className="bg-gradient-to-r from-indigo-300 via-indigo-400 to-cyan-300 bg-clip-text text-transparent"> actually trading it</span>
          </h1>

          <p className="mx-auto mt-4 max-w-xl text-white/60">
            A safe sandbox for VU Kaunas faculty students to learn how a
            cryptocurrency exchange works — swap KNF Coin and Litecoin
            Testnet4 and watch every order settle on-chain.
          </p>

          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <Link
              to="/exchange"
              className="rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-600 px-6 py-3 font-bold text-white shadow-lg shadow-indigo-500/30 transition-all hover:brightness-110 active:translate-y-px"
            >
              Start swapping
            </Link>
            <LiveRateChip />
          </div>
        </section>


        {/* Tool cards */}
        <section className="mt-10 grid grid-cols-1 gap-4 md:grid-cols-2">
          <ToolCard
            to="/exchange"
            icon="⇄"
            title="Exchange"
            description="Swap KNF Coin and Litecoin Testnet4, then follow your order from deposit to payout."
          />
          <ToolCard
            href="/explorer/"
            icon="⛓"
            title="Block Explorer"
            description="Browse KNF Coin blocks, transactions and addresses in real time — including your own swaps."
          />
        </section>


        {/* How it works */}
        <section className="mt-10 rounded-2xl border border-white/10 bg-white/[0.045] p-6 backdrop-blur-xl md:p-8">
          <h2 className="text-xl font-bold text-white">How a swap works</h2>

          <div className="mt-5 grid grid-cols-1 gap-6 md:grid-cols-3">
            <HowItWorksStep
              number="1"
              title="Create an order"
              description="Pick a direction and amount, and tell us the address you want to receive on."
            />
            <HowItWorksStep
              number="2"
              title="Send your deposit"
              description="Pay the unique deposit address (or scan its QR code) before the order expires."
            />
            <HowItWorksStep
              number="3"
              title="Receive on-chain"
              description="Once your deposit confirms, the exchange pays out to your address automatically — or, if it cannot, sends your coins back."
            />
          </div>
        </section>
      </div>
    </Layout>
  )
}
