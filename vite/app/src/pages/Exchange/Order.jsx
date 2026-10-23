// -----------------------------------------------------------
//  [*] Order — one order's status page (/exchange/order/:orderId)
//
//  Shows a single order and polls the backend every 2 seconds
//  so the student watches it move through the pipeline:
//  awaiting_deposit -> awaiting_confirmations -> exchanging ->
//  sending -> completed (or expired, or failed) — and back
//  again when the chain takes a deposit away. An order that
//  cannot go through goes refunding -> refunded instead: its
//  coins are sent back to the addresses they came from. A
//  completed order whose deposit the chain took back after
//  the payout is reversed.
//
//  One column of cards over the page's full width, read top
//  to bottom:
//    - the swap: what is sent and received — or sent back —
//      the rate, and a note when a different amount arrived
//    - the status: what is happening now in plain words, the
//      reason when the order could not go through, the steps
//      of the pipeline, and a delayed payout's notice
//    - while the deposit is awaited, the payment: the QR code
//      and the address to pay, the amount and the time left
//      (once coins arrive the order can no longer expire, and
//      the address is no longer offered to pay)
//    - the coins sent back, refund by refund
//    - the details: the addresses (with a warning once the
//      deposit address takes no more coins) and the
//      transactions
//
//  The backend owns the order; there is no local fallback, so
//  a fetch failure shows a real error.
//
//  Split into (root component last):
//
//    formatAmount    — a coin amount for display
//    useCountdown    — the time left, ticking every second
//    formatCountdown — the time left as mm:ss
//    formatDateTime  — the creation time in local time
//    statusStory     — what the status card says
//    Callout         — a notice in one of the tones
//    ProgressSteps   — the pipeline's steps
//    StatusCard      — the status, its steps and notices
//    PaymentCard     — QR, address and countdown to pay
//    SwapSide        — one side of the swap
//    SwapCard        — the swap, its rate and its surprises
//    RefundCard      — the coins sent back
//    ChainChip       — whether the chain holds a transaction
//    DetailRow       — one row of the details
//    DetailsCard     — addresses and transactions
//    Order           — the page (default export)
// -----------------------------------------------------------

import { useEffect, useState } from 'react'
import { useParams, Link } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import {
  LuArrowDown, LuArrowLeft, LuArrowRight, LuCircleCheckBig, LuCircleX, LuClock, LuHourglass, LuInfo, LuLock, LuRefreshCw,
  LuSend, LuShieldCheck, LuTriangleAlert, LuUndo2,
} from 'react-icons/lu'

import { ExchangeApi } from './lib/api.js'
import { ORDER_STATUS, hasReceivedCoins, payoutConfirming, sendsCoinsBack, shownStatus, takesCoins } from './lib/orders.js'
import Layout from './components/Layout.jsx'
import CoinIcon from './components/CoinIcon.jsx'
import StatusBadge from './components/StatusBadge.jsx'
import CopyableAddress from './components/CopyableAddress.jsx'


// How often the order is read again while the page is open
const POLL_INTERVAL_MS = 2000

// The pipeline in display order; each step lights up as the
// order's status reaches it — an expired order stopped at its
// deposit, a failed one at its payout, a reversed one short
// of done
const TIMELINE_STEPS = [
  { statuses: [ORDER_STATUS.AWAITING_DEPOSIT, ORDER_STATUS.EXPIRED], label: 'Deposit' },
  { statuses: [ORDER_STATUS.AWAITING_CONFIRMATIONS],                 label: 'Confirming' },
  { statuses: [ORDER_STATUS.EXCHANGING],                             label: 'Exchanging' },
  { statuses: [ORDER_STATUS.SENDING, ORDER_STATUS.FAILED],           label: 'Sending' },
  { statuses: [ORDER_STATUS.COMPLETED, ORDER_STATUS.REVERSED],       label: 'Done' },
]

// The pipeline of an order whose coins go back instead: the
// same up to the rate lock, then the refund
const REFUND_TIMELINE_STEPS = [
  ...TIMELINE_STEPS.slice(0, 3),
  { statuses: [ORDER_STATUS.REFUNDING],                              label: 'Sending back' },
  { statuses: [ORDER_STATUS.REFUNDED],                               label: 'Sent back' },
]

// The look of every card on the page
const CARD = 'rounded-2xl border border-white/10 bg-white/[0.045] p-5 backdrop-blur-xl sm:p-6'

// The look of the small uppercase label over a figure
const LABEL = 'text-xs font-bold uppercase tracking-widest text-white/50'

// The colours of a tone: the round badge of the status card's
// icon, and a notice's box
const TONES = {
  indigo:  { badge: 'bg-indigo-500/15 text-indigo-300 ring-indigo-400/30',   callout: 'border-indigo-400/25 bg-indigo-500/10 text-indigo-100' },
  emerald: { badge: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/30', callout: 'border-emerald-400/25 bg-emerald-500/10 text-emerald-100' },
  amber:   { badge: 'bg-amber-500/15 text-amber-300 ring-amber-400/30',      callout: 'border-amber-400/30 bg-amber-500/10 text-amber-100' },
  orange:  { badge: 'bg-orange-500/15 text-orange-300 ring-orange-400/30',   callout: 'border-orange-400/30 bg-orange-500/10 text-orange-100' },
  red:     { badge: 'bg-red-500/15 text-red-300 ring-red-400/30',            callout: 'border-red-400/30 bg-red-500/10 text-red-100' },
  sky:     { badge: 'bg-sky-500/15 text-sky-300 ring-sky-400/30',            callout: 'border-sky-400/25 bg-sky-500/10 text-sky-100' },
  neutral: { badge: 'bg-white/[0.08] text-white/70 ring-white/15',           callout: 'border-white/15 bg-white/[0.05] text-white/80' },
}

// A step's circle: done (green, or orange on the way back),
// the current one, where a stopped order stopped, and ahead
const STEP_CIRCLES = {
  done:     'border-emerald-400/40 bg-emerald-500/15 text-emerald-300',
  doneBack: 'border-orange-400/40 bg-orange-500/15 text-orange-300',
  current:  'border-indigo-400/70 bg-indigo-500/20 text-indigo-200 ring-4 ring-indigo-500/15',
  currentBack: 'border-orange-400/70 bg-orange-500/20 text-orange-200 ring-4 ring-orange-500/15',
  expired:  'border-amber-400/50 bg-amber-500/15 text-amber-300',
  failed:   'border-red-400/50 bg-red-500/15 text-red-300',
  ahead:    'border-white/15 bg-white/[0.03] text-white/40',
}

// The line leading into a step, coloured like the way there
const STEP_LINES = {
  done:     'before:bg-emerald-400/40',
  doneBack: 'before:bg-orange-400/40',
  current:  'before:bg-indigo-400/40',
  currentBack: 'before:bg-orange-400/40',
  expired:  'before:bg-white/10',
  failed:   'before:bg-red-400/30',
  ahead:    'before:bg-white/10',
}

// The chip beside a reversed order's transactions: one the
// chain holds, and one a reorganisation took back out of it
const CHAIN_CHIPS = {
  in:  { Icon: LuCircleCheckBig, text: 'In the main chain',           classes: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200' },
  out: { Icon: LuTriangleAlert,  text: 'No longer in the main chain', classes: 'border-red-400/30 bg-red-500/10 text-red-200' },
}







// -----------------------------------------------------------
// formatAmount
// -----------------------------------------------------------
//
// A coin amount for display: up to 8 decimals in the
// runtime's locale, no trailing noise, and nothing at all for
// a value that is not a number.
//
// Used by:
//   - statusStory, PaymentCard, SwapCard, RefundCard (below)
// -----------------------------------------------------------

const formatAmount = (value) => {
  const n = Number(value)
  if (!Number.isFinite(n)) return ''
  return n.toLocaleString(undefined, { maximumFractionDigits: 8 })
}







// -----------------------------------------------------------
// useCountdown
// -----------------------------------------------------------
//
// The milliseconds left until targetTs, never below zero;
// the component re-renders once a second to keep it current.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function useCountdown(targetTs) {

  const [now, setNow] = useState(Date.now())


  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [])


  return Math.max(0, targetTs - now)
}







// -----------------------------------------------------------
// formatCountdown
// -----------------------------------------------------------
//
// Milliseconds as minutes and seconds, both two digits — the
// countdown the page shows while the deposit is awaited.
//
// Used by:
//   - PaymentCard (below)
// -----------------------------------------------------------

function formatCountdown(ms) {
  const totalSeconds = Math.floor(ms / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
}







// -----------------------------------------------------------
// formatDateTime
// -----------------------------------------------------------
//
// An epoch-milliseconds time as date and time to the second,
// in the browser's local time zone — the order's creation
// time under its title.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function formatDateTime(timestamp) {
  const date = new Date(timestamp)
  const pad = (n) => String(n).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
         `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
}







// -----------------------------------------------------------
// statusStory
// -----------------------------------------------------------
//
// What the status card tells about an order, in plain words:
// a headline for its status, a sentence on what happens now
// or what became of it, the tone and icon that colour it —
// and, for an order that could not go through, the backend's
// reason. A status the page does not know is named as the
// backend wrote it.
//
// Used by:
//   - StatusCard (below)
// -----------------------------------------------------------

function statusStory(order) {
  switch (order.status) {
    case ORDER_STATUS.AWAITING_DEPOSIT:
      return {
        tone: 'indigo', Icon: LuHourglass, title: 'Waiting for your deposit',
        text: 'Send the coins to the address below. The order expires if nothing arrives before the time runs out.',
      }
    case ORDER_STATUS.AWAITING_CONFIRMATIONS:
      return {
        tone: 'indigo', Icon: LuShieldCheck, title: 'Confirming your deposit',
        text: `${formatAmount(order.receivedAmount)} ${order.fromAsset} arrived. No time limit any more — the swap completes automatically once the network has confirmed it.`,
      }
    case ORDER_STATUS.EXCHANGING:
      return {
        tone: 'indigo', Icon: LuLock, title: 'Locking the rate',
        text: 'Your deposit is confirmed. The exchange is locking the rate and pricing your payout.',
      }
    case ORDER_STATUS.SENDING:
      return {
        tone: 'indigo', Icon: LuSend, title: `Sending your ${order.toAsset}`,
        text: 'Your deposit is confirmed and the rate is locked — the payout goes out to your address next.',
      }
    case ORDER_STATUS.COMPLETED:
      return {
        tone: 'emerald', Icon: LuCircleCheckBig, title: 'Swap complete',
        text: `${formatAmount(order.toAmount)} ${order.toAsset} were paid out to your address.`,
      }
    case ORDER_STATUS.REFUNDING:
      return {
        tone: 'orange', Icon: LuUndo2, title: 'Sending your coins back', reason: order.error,
        text: `This order could not be exchanged, so your ${order.fromAsset} are on their way back to the address they came from.`,
      }
    case ORDER_STATUS.REFUNDED:
      return {
        tone: 'orange', Icon: LuUndo2, title: 'Coins sent back', reason: order.error,
        text: `This order could not be exchanged, so your ${order.fromAsset} went back to the address they came from.`,
      }
    case ORDER_STATUS.EXPIRED:
      return {
        tone: 'amber', Icon: LuClock, title: 'Order expired',
        text: 'Nothing arrived before the deadline. Coins that still arrive within a day are exchanged after all — otherwise, create a new order.',
      }
    case ORDER_STATUS.FAILED:
      return {
        tone: 'red', Icon: LuCircleX, title: 'Order failed', reason: order.error,
        text: 'This order could not be exchanged, and its coins could not be sent back either.',
      }
    case ORDER_STATUS.REVERSED:
      return {
        tone: 'red', Icon: LuTriangleAlert, title: 'Deposit reversed',
        text: `${formatAmount(order.toAmount)} ${order.toAsset} were paid out, but a reorganisation of the ${order.fromAsset} chain then took your deposit back out of it. The exchange paid for coins the chain no longer holds.`,
      }
    default:
      return { tone: 'neutral', Icon: LuInfo, title: `Status: ${order.status}`, text: '' }
  }
}







// -----------------------------------------------------------
// Callout
// -----------------------------------------------------------
//
// A notice in one of the page's tones: its icon, an optional
// title and the message under it. Every notice on the page
// looks like this, whatever it is about.
//
// Used by:
//   - StatusCard, SwapCard, Order (below)
// -----------------------------------------------------------

function Callout({ tone, icon, title, children }) {

  // JSX reads a capitalised name as a component, a lowercase
  // one as an HTML tag
  const Icon = icon


  return (
    <div className={`flex gap-3 rounded-xl border px-4 py-3 text-[13px] leading-relaxed ${TONES[tone].callout}`}>
      <Icon aria-hidden="true" className="mt-0.5 h-4 w-4 shrink-0" />
      <div className="min-w-0">
        {title && <div className="font-semibold">{title}</div>}
        <div className={title ? 'opacity-85' : ''}>{children}</div>
      </div>
    </div>
  )
}







// -----------------------------------------------------------
// ProgressSteps
// -----------------------------------------------------------
//
// The five steps of the pipeline as a list, each a numbered
// circle under the line leading into it. Steps passed show a
// check mark, the current one a spinner (and, while
// confirming, the confirmations seen of those required); an
// expired order stops at its deposit, a failed one at its
// payout and a reversed one short of done, marked there. An
// order whose coins go back follows the refund's steps after
// the rate lock, in orange. On a narrow screen only the step
// the order is at keeps its label — five would not fit side
// by side.
//
// Used by:
//   - StatusCard (below)
// -----------------------------------------------------------

function ProgressSteps({ order }) {

  const isRefund = sendsCoinsBack(order)
  const isFinished = order.status === ORDER_STATUS.COMPLETED || order.status === ORDER_STATUS.REFUNDED
  const stoppedAs = { [ORDER_STATUS.EXPIRED]: 'expired', [ORDER_STATUS.FAILED]: 'failed', [ORDER_STATUS.REVERSED]: 'failed' }[order.status] ?? null

  const steps = isRefund ? REFUND_TIMELINE_STEPS : TIMELINE_STEPS
  const activeIndex = steps.findIndex((step) => step.statuses.includes(order.status))

  // How a step stands: passed, current, where the order stopped, or ahead
  const stateOf = (i) => {
    const back = isRefund && i >= 3 ? 'Back' : ''
    if (isFinished || (activeIndex >= 0 && i < activeIndex)) return `done${back}`
    if (i === activeIndex) return stoppedAs ?? `current${back}`
    return 'ahead'
  }


  return (
    <ol aria-label="Order progress" className="mt-6 grid grid-cols-5 gap-1">
      {steps.map((step, i) => {
        const state = stateOf(i)
        const isCurrent = state.startsWith('current')
        const isWhereItIs = i === activeIndex

        return (
          <li
            key={step.label}
            aria-current={isCurrent ? 'step' : undefined}
            className={
              'relative flex flex-col items-center text-center ' +
              (i > 0
                ? 'before:absolute before:right-[calc(50%+1.25rem)] before:top-4 before:h-0.5 before:w-[calc(100%-2.5rem)] before:rounded-full ' + STEP_LINES[state]
                : '')
            }
          >
            <span aria-hidden="true" className={`relative grid h-8 w-8 place-items-center rounded-full border text-xs font-bold ${STEP_CIRCLES[state]}`}>
              {state.startsWith('done')
                ? '✓'
                : isCurrent
                  ? <span className="h-3.5 w-3.5 animate-spin rounded-full border-2 border-current border-t-transparent" />
                  : state === 'expired' ? '!' : state === 'failed' ? '✕' : i + 1}
            </span>
            <span className={`mt-2 text-[11px] font-semibold leading-tight sm:block sm:text-xs ${isWhereItIs ? 'block' : 'hidden'} ${state === 'ahead' ? 'text-white/40' : 'text-white/85'}`}>
              {step.label}
            </span>
            {isCurrent && order.status === ORDER_STATUS.AWAITING_CONFIRMATIONS && (
              <span className="mt-0.5 text-[11px] tabular-nums text-indigo-200/80">
                {order.confirmCount} of {order.confirmTarget}
              </span>
            )}
          </li>
        )
      })}
    </ol>
  )
}







// -----------------------------------------------------------
// StatusCard
// -----------------------------------------------------------
//
// The first card: the story of the order's status beside its
// icon — the backend's reason under it when the order could
// not go through, and a small note while a payout already
// out is confirming — the steps of the pipeline, and a notice
// when a payout is delayed: it is retried automatically, the
// backend's own words kept small beneath for whoever needs
// them.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function StatusCard({ order, confirming }) {

  const story = statusStory(order)
  const isPayoutDelayed = order.status === ORDER_STATUS.SENDING && Boolean(order.error)


  return (
    <section aria-label="Order status" aria-live="polite" className={CARD}>
      <div className="flex items-start gap-4">
        <span className={`grid h-11 w-11 shrink-0 place-items-center rounded-full ring-1 ${TONES[story.tone].badge}`}>
          <story.Icon aria-hidden="true" className="h-5 w-5" />
        </span>
        <div className="min-w-0 pt-0.5">
          <h2 className="text-lg font-bold text-white sm:text-xl">{story.title}</h2>
          {story.text && <p className="mt-1 text-sm leading-relaxed text-white/65">{story.text}</p>}
          {story.reason && (
            <p className="mt-2 text-[13px] text-white/50">
              <span className="font-semibold text-white/70">Reason:</span> {story.reason}
            </p>
          )}
          {confirming && (
            <div className="mt-3">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-indigo-400/30 bg-indigo-500/10 px-2.5 py-1 text-xs font-semibold text-indigo-200">
                <span aria-hidden="true" className="h-3 w-3 animate-spin rounded-full border-2 border-current border-t-transparent" />
                Payout confirming
              </span>
            </div>
          )}
        </div>
      </div>

      <ProgressSteps order={order} />

      {isPayoutDelayed && (
        <div className="mt-5">
          <Callout tone="amber" icon={LuTriangleAlert} title="Payout delayed">
            It could not be sent yet — the exchange keeps trying automatically, there is nothing to do on your side.
            <span className="mt-1 block break-all font-mono text-[11px] opacity-70">{order.error}</span>
          </Callout>
        </div>
      )}
    </section>
  )
}







// -----------------------------------------------------------
// PaymentCard
// -----------------------------------------------------------
//
// While the deposit is awaited: the QR code of the deposit
// address captioned with the amount to pay, the address to
// copy, the reminder that the rate locks on confirmation,
// and the time left — amber in its last five minutes.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function PaymentCard({ order, timeLeft }) {
  return (
    <section aria-label="Payment" className={`${CARD} grid gap-6 sm:grid-cols-[auto_minmax(0,1fr)] sm:items-center`}>
      <figure className="mx-auto">
        <div role="img" aria-label="QR code of the deposit address" className="rounded-2xl bg-white p-3 shadow-lg shadow-black/30">
          <QRCodeSVG value={order.depositAddress || ''} size={168} />
        </div>
        <figcaption className="mt-2.5 text-center text-xs text-white/55">
          {`Scan to pay ${formatAmount(order.fromAmount)} ${order.fromAsset}`}
        </figcaption>
      </figure>

      <div className="grid min-w-0 gap-5">
        <div>
          <div className="mb-2 text-sm text-white/80">
            <strong className="text-white">Send</strong> {formatAmount(order.fromAmount)} {order.fromAsset} to this address:
          </div>
          <CopyableAddress value={order.depositAddress} />
          <p className="mt-2.5 text-[13px] text-white/55">The final rate is locked in once your deposit confirms.</p>
        </div>

        <div className="flex items-center gap-3 rounded-xl border border-white/[0.08] bg-black/20 px-4 py-3">
          <LuClock aria-hidden="true" className="h-5 w-5 shrink-0 text-white/40" />
          <div>
            <div className={LABEL}>Time remaining</div>
            <div className={`text-2xl font-extrabold tabular-nums ${timeLeft < 5 * 60 * 1000 ? 'text-amber-300' : 'text-white'}`}>
              {formatCountdown(timeLeft)}
            </div>
          </div>
        </div>
      </div>
    </section>
  )
}







// -----------------------------------------------------------
// SwapSide
// -----------------------------------------------------------
//
// One side of the swap: the coin's logo (or its dot), and
// under a small label the amount with the asset's name —
// struck through for a payout that will not happen.
//
// Used by:
//   - SwapCard (below) — twice
// -----------------------------------------------------------

function SwapSide({ label, asset, icon, amount, struck = false }) {
  return (
    <div className="flex min-w-0 items-center gap-3">
      <CoinIcon asset={asset} icon={icon} size={40} />
      <div className="min-w-0">
        <div className={LABEL}>{label}</div>
        <div className={`break-words text-lg font-extrabold sm:text-xl ${struck ? 'text-white/40 line-through' : 'text-white'}`}>
          {amount} {asset}
        </div>
      </div>
    </div>
  )
}







// -----------------------------------------------------------
// SwapCard
// -----------------------------------------------------------
//
// What the swap is about: the amount sent — agreed while the
// deposit is awaited, received once coins arrive, struck
// through once the chain took it back after the payout — and
// what comes back for it: the payout, estimated until the
// rate is locked and exact after (received, once the order is
// done), struck through on an order that failed, or for an
// order that did not go through, what is sent back (exactly
// what its refunds pay, about what arrived before there are
// any).
// Under it the rate, quoted or locked, for an order still
// going through or done; and a note when a different amount
// arrived than was agreed — compared in satoshis, so float
// noise is none.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function SwapCard({ order }) {

  const isRefund = sendsCoinsBack(order)
  const isFailed = order.status === ORDER_STATUS.FAILED
  const isExpired = order.status === ORDER_STATUS.EXPIRED
  const isReversed = order.status === ORDER_STATUS.REVERSED

  // Coins the student really sent: none while the order waits for its
  // deposit or after it expired, whatever amount it may still carry
  const hasCoins = hasReceivedCoins(order)
  const sentAmount = hasCoins ? order.receivedAmount : order.fromAmount

  // The payout: exact once the backend locked the rate, estimated from
  // what was sent before that
  const isLocked = order.lockedRate != null
  const receiveAmount = isLocked ? order.toAmount : sentAmount * order.rate

  // What goes back to an order that did not go through
  const sentBack = order.refunds.flatMap((refund) => refund.recipients).reduce((sum, recipient) => sum + Number(recipient.amount), 0)

  const toSat = (v) => Math.round(Number(v) * 1e8)
  const hasAmountMismatch =
    hasCoins && !isFailed && !isRefund && toSat(order.receivedAmount) !== toSat(order.fromAmount)


  return (
    <section aria-label="Swap" className={`${CARD} bg-gradient-to-br from-indigo-500/[0.12] via-white/[0.03] to-cyan-500/[0.08]`}>
      <div className="grid items-center gap-4 sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]">
        <SwapSide
          label={isReversed ? 'Deposit reversed' : hasCoins ? 'You sent' : 'You send'}
          asset={order.fromAsset}
          icon={order.fromIcon}
          amount={formatAmount(sentAmount)}
          struck={isReversed}
        />

        <span aria-hidden="true" className="grid h-9 w-9 place-items-center rounded-full border border-white/10 bg-black/20 text-white/50">
          <LuArrowRight className="hidden h-4 w-4 sm:block" />
          <LuArrowDown className="h-4 w-4 sm:hidden" />
        </span>

        {isRefund ? (
          <SwapSide
            label="Sent back to you"
            asset={order.fromAsset}
            icon={order.fromIcon}
            amount={order.refunds.length > 0 ? formatAmount(sentBack) : `≈${formatAmount(order.receivedAmount)}`}
          />
        ) : (
          <SwapSide
            label={isFailed ? 'Not paid out' : order.status === ORDER_STATUS.COMPLETED || isReversed ? 'You received' : 'You receive'}
            asset={order.toAsset}
            icon={order.toIcon}
            amount={isLocked ? formatAmount(receiveAmount) : `≈${formatAmount(receiveAmount)}`}
            struck={isFailed}
          />
        )}
      </div>

      {!isRefund && !isFailed && !isExpired && (
        <div className="mt-5 flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-white/[0.08] pt-4 text-sm">
          <span className="text-white/50">Rate</span>
          <span className="text-white/85">
            1 {order.fromAsset} ≈ {formatAmount(order.lockedRate ?? order.rate)} {order.toAsset}
          </span>
          <span className="ml-auto rounded-full bg-white/[0.06] px-2 py-0.5 text-[11px] font-semibold text-white/55">
            {isLocked ? 'Locked' : 'Quoted'}
          </span>
        </div>
      )}

      {hasAmountMismatch && (
        <div className="mt-4">
          <Callout tone="sky" icon={LuInfo}>
            {`You sent ${formatAmount(order.receivedAmount)} ${order.fromAsset} instead of the agreed ${formatAmount(order.fromAmount)} — the payout follows what actually arrived.`}
          </Callout>
        </div>
      )}
    </section>
  )
}







// -----------------------------------------------------------
// RefundCard
// -----------------------------------------------------------
//
// What an order sent back, one entry per address paid: the
// amount (the network fee already taken off), whether the
// refund has confirmed, the address it went to — "the
// address it came from" for one the backend cannot name —
// and its transaction. Headed as the coins that came after
// the rate lock for an order that was exchanged, and as the
// student's own coins for one that was not. Nothing for an
// order without refunds.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function RefundCard({ order }) {

  if (order.refunds.length === 0) return null

  // Exchanged, or about to be: what it sent back came on top
  const wasExchanged = order.status === ORDER_STATUS.SENDING || order.status === ORDER_STATUS.COMPLETED


  return (
    <section aria-label="Coins sent back" className="rounded-2xl border border-orange-400/25 bg-orange-500/[0.06] p-5 backdrop-blur-xl sm:p-6">
      <h2 className="flex items-center gap-2 text-sm font-bold text-orange-200">
        <LuUndo2 aria-hidden="true" className="h-4 w-4" />
        {wasExchanged ? 'Sent back — these arrived after the rate was locked' : `Your ${order.fromAsset} sent back`}
      </h2>

      {/* Keyed by position: refunds are only ever added after the others */}
      <ul className="mt-3 grid gap-2.5">
        {order.refunds.map((refund, i) => refund.recipients.map((recipient, j) => (
          <li key={`${i}-${j}`} className="rounded-xl border border-white/[0.08] bg-black/20 px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-base font-bold text-white">{formatAmount(recipient.amount)} {order.fromAsset}</span>
              <span className={
                'rounded-full px-2 py-0.5 text-[11px] font-semibold ' +
                (refund.confirmed ? 'bg-emerald-500/15 text-emerald-300' : 'bg-orange-500/15 text-orange-200')
              }>
                {refund.confirmed ? 'Confirmed' : 'Confirming…'}
              </span>
            </div>
            <div className="mt-1 text-[13px] text-white/60">
              to <span className="break-all font-mono text-white/80">{recipient.address ?? 'the address it came from'}</span>
            </div>
            <div className="mt-1.5 break-all font-mono text-[11px] text-white/40">Refund tx: {refund.txid}</div>
          </li>
        )))}
      </ul>
    </section>
  )
}







// -----------------------------------------------------------
// ChainChip
// -----------------------------------------------------------
//
// Beside a transaction id on a reversed order: whether the
// main chain holds that transaction — green for the payout,
// red for the deposit a reorganisation took back out of it.
//
// Used by:
//   - DetailsCard (below)
// -----------------------------------------------------------

function ChainChip({ inChain }) {

  const chip = inChain ? CHAIN_CHIPS.in : CHAIN_CHIPS.out


  return (
    <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${chip.classes}`}>
      <chip.Icon aria-hidden="true" className="h-3.5 w-3.5" />
      {chip.text}
    </span>
  )
}







// -----------------------------------------------------------
// DetailRow
// -----------------------------------------------------------
//
// One row of the details: the label on the left — above, on a
// narrow screen — and the value beside it.
//
// Used by:
//   - DetailsCard (below)
// -----------------------------------------------------------

function DetailRow({ label, children }) {
  return (
    <div className="grid gap-1.5 py-3 first:pt-0 last:pb-0 sm:grid-cols-[170px_minmax(0,1fr)] sm:items-baseline sm:gap-4">
      <dt className="text-sm text-white/50">{label}</dt>
      <dd className="min-w-0 text-sm text-white/85">{children}</dd>
    </div>
  )
}







// -----------------------------------------------------------
// DetailsCard
// -----------------------------------------------------------
//
// The order's particulars: the deposit address (the payment
// card shows it while the deposit is awaited) — warned
// against once the rate is locked, since coins sent to it
// then are not exchanged but sent back (no warning on a
// reversed order) — the student's own address the payout
// goes to (not for an order whose coins go back), and the
// deposit and payout transactions once there are any: on a
// reversed order, each with a chip telling whether the main
// chain still holds it.
//
// Used by:
//   - Order (below)
// -----------------------------------------------------------

function DetailsCard({ order }) {

  const isAwaitingDeposit = order.status === ORDER_STATUS.AWAITING_DEPOSIT
  const isExpired = order.status === ORDER_STATUS.EXPIRED
  const isReversed = order.status === ORDER_STATUS.REVERSED


  return (
    <section aria-label="Order details" className={CARD}>
      <h2 className={LABEL}>Details</h2>

      <dl className="mt-4 divide-y divide-white/[0.07]">
        {!isAwaitingDeposit && (
          <DetailRow label="Deposit address">
            <CopyableAddress value={order.depositAddress} />
            {!takesCoins(order) && !isExpired && !isReversed && (
              <p className="mt-3 flex w-fit max-w-full items-start gap-2 rounded-lg border border-amber-400/30 bg-amber-500/10 px-3 py-2 text-xs font-medium leading-relaxed text-amber-200">
                <LuTriangleAlert aria-hidden="true" className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-300" />
                <span>Do not send more to this address — this order takes no more coins. Anything that arrives within a day goes back to the address it came from.</span>
              </p>
            )}
          </DetailRow>
        )}

        {!sendsCoinsBack(order) && (
          <DetailRow label={`Your ${order.toAsset} address`}>
            <CopyableAddress value={order.destination} />
          </DetailRow>
        )}

        {order.txDepositId && (
          <DetailRow label="Deposit transaction">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="break-all font-mono text-xs text-white/70">{order.txDepositId}</span>
              {isReversed && <ChainChip inChain={false} />}
            </div>
          </DetailRow>
        )}

        {order.txSendId && (
          <DetailRow label="Payout transaction">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
              <span className="break-all font-mono text-xs text-white/70">{order.txSendId}</span>
              {isReversed && <ChainChip inChain />}
            </div>
          </DetailRow>
        )}
      </dl>
    </section>
  )
}







// -----------------------------------------------------------
// Order (default export)
// -----------------------------------------------------------
//
// The page component: polls the order and lays out its cards,
// one column over the page's full width, under the title row
// — the arrow back to the exchange, the id, the creation time
// and the status — the swap first, so what goes in and comes
// out is the first thing read. The order is shown with the
// status the pages show it with: done as soon as its payout
// is out, the status card noting the payout is confirming.
// Until the first answer it says it is loading; an order it
// could not load at all is "Order not found", with the
// reason, while a poll that fails once the order is on screen
// keeps it there under a reconnecting notice.
//
// Used by:
//   - App.jsx — route /exchange/order/:orderId
// -----------------------------------------------------------

export default function Order() {

  const { orderId } = useParams()

  const [order, setOrder] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)


  // Poll the order until the component unmounts. A failed poll only
  // replaces the page with an error when we never managed to load the
  // order at all; once loaded, the last known state stays on screen with
  // a "reconnecting" note so a blip in the connection does not look like
  // the order vanished.
  useEffect(() => {
    let stop = false

    const load = async () => {
      try {
        const remote = await ExchangeApi.getOrder(orderId)
        if (stop) return
        setOrder(remote)
        setError(null)
        setLoading(false)
      } catch (err) {
        if (stop) return
        setError(err.message || 'Failed to load order')
        setLoading(false)
      }
    }

    load()
    const interval = setInterval(load, POLL_INTERVAL_MS)
    return () => { stop = true; clearInterval(interval) }
  }, [orderId])


  // Hooks must run unconditionally, so compute the countdown before any
  // early return below.
  const timeLeft = useCountdown(order?.expiresAt || 0)


  // Loading / error states
  if (loading) {
    return (
      <Layout>
        <div className="grid place-items-center py-24">
          <span className="h-8 w-8 animate-spin rounded-full border-[3px] border-indigo-300/30 border-t-indigo-300" />
          <p className="mt-4 text-white/60">Loading order...</p>
        </div>
      </Layout>
    )
  }

  if (!order) {
    return (
      <Layout>
        <div className={`mx-auto mt-10 max-w-[560px] text-center ${CARD}`}>
          <h1 className="text-3xl font-extrabold text-white">Order not found</h1>
          {error && <p className="mt-2 text-red-400">{error}</p>}
          <Link
            to="/exchange"
            className="mt-6 inline-block rounded-xl bg-gradient-to-r from-indigo-500 to-cyan-600 px-6 py-3 font-bold text-white shadow-lg shadow-indigo-500/30 transition-all hover:brightness-110"
          >
            Back to Exchange
          </Link>
        </div>
      </Layout>
    )
  }


  // Done as soon as its payout is out; its confirmations come after
  const shown = { ...order, status: shownStatus(order) }


  return (
    <Layout>
      <div>

        {/* Connection hiccup while polling — keep showing the last known
            state instead of pretending the order disappeared */}
        {error && (
          <div className="mb-4">
            <Callout tone="amber" icon={LuRefreshCw}>
              Connection lost — retrying... The data below may be a few seconds old.
            </Callout>
          </div>
        )}

        {/* Title row — the page's only way back to the exchange is the
            arrow on the title's left: an icon alone, so the link carries
            its name for a screen reader and a tooltip for the mouse */}
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div className="grid min-w-0 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 gap-y-1 sm:gap-x-4">
            <Link
              to="/exchange"
              aria-label="Back to Exchange"
              title="Back to Exchange"
              className="grid h-9 w-9 place-items-center rounded-xl border border-white/15 bg-white/[0.05] text-white/80 transition-colors hover:border-indigo-400/60 hover:bg-white/[0.09] hover:text-white sm:h-10 sm:w-10"
            >
              <LuArrowLeft aria-hidden="true" className="h-5 w-5" />
            </Link>
            <h1 className="text-2xl font-extrabold tracking-tight text-white sm:text-3xl">
              Order <span className="font-mono text-indigo-300">#{order.id}</span>
            </h1>
            <p className="col-start-2 text-sm text-white/50">Created {formatDateTime(order.createdAt)}</p>
          </div>
          <StatusBadge status={shown.status} />
        </div>


        <div className="grid gap-4">
          <SwapCard order={shown} />
          <StatusCard order={shown} confirming={payoutConfirming(order)} />
          {order.status === ORDER_STATUS.AWAITING_DEPOSIT && <PaymentCard order={order} timeLeft={timeLeft} />}
          <RefundCard order={shown} />
          <DetailsCard order={shown} />
        </div>
      </div>
    </Layout>
  )
}
