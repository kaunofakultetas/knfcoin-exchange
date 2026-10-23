// -----------------------------------------------------------
//  [*] StatusBadge — an order's status as a pill
//
//  Small pill showing an order's lifecycle status. One entry
//  per backend status string (see lib/orders.js); anything
//  unknown falls back to a neutral grey pill so a new backend
//  status can never crash the UI.
//
//  In-flight statuses get a pulsing dot so students can see at
//  a glance which orders are still moving.
//
//  Used by:
//    - pages/Exchange/Exchange.jsx — recent orders list
//    - pages/Exchange/Order.jsx    — status line
// -----------------------------------------------------------

import { ORDER_STATUS } from '../lib/orders.js'


// Visuals per status: label, pill colours and whether the
// order is still in flight (shows the pulsing dot).
const STATUS_STYLES = {
  [ORDER_STATUS.AWAITING_DEPOSIT]:       { label: 'Awaiting deposit', classes: 'bg-sky-500/15 text-sky-300 ring-sky-400/30',          live: true },
  [ORDER_STATUS.AWAITING_CONFIRMATIONS]: { label: 'Confirming',       classes: 'bg-indigo-500/15 text-indigo-300 ring-indigo-400/30', live: true },
  [ORDER_STATUS.EXCHANGING]:             { label: 'Exchanging',       classes: 'bg-violet-500/15 text-violet-300 ring-violet-400/30', live: true },
  [ORDER_STATUS.SENDING]:                { label: 'Sending',          classes: 'bg-cyan-500/15 text-cyan-300 ring-cyan-400/30',       live: true },
  [ORDER_STATUS.REFUNDING]:              { label: 'Refunding',        classes: 'bg-orange-500/15 text-orange-300 ring-orange-400/30', live: true },
  [ORDER_STATUS.COMPLETED]:              { label: 'Completed',        classes: 'bg-emerald-500/15 text-emerald-300 ring-emerald-400/30' },
  [ORDER_STATUS.EXPIRED]:                { label: 'Expired',          classes: 'bg-amber-500/15 text-amber-300 ring-amber-400/30' },
  [ORDER_STATUS.REFUNDED]:               { label: 'Refunded',         classes: 'bg-slate-400/15 text-slate-200 ring-slate-300/30' },
  [ORDER_STATUS.FAILED]:                 { label: 'Failed',           classes: 'bg-red-500/15 text-red-300 ring-red-400/30' },
  [ORDER_STATUS.REVERSED]:               { label: 'Reversed',         classes: 'bg-rose-500/15 text-rose-300 ring-rose-400/30' },
}







// -----------------------------------------------------------
// StatusBadge (default export)
// -----------------------------------------------------------
//
// The pill of one status: its label and colours from the
// table above, or the backend's own string on grey for a
// status this table does not know.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function StatusBadge({ status }) {

  const style = STATUS_STYLES[status] ?? {
    label: status,
    classes: 'bg-white/[0.08] text-white/70 ring-white/[0.15]',
  }


  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold leading-none ring-1 ${style.classes}`}>
      {style.live && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />}
      {style.label}
    </span>
  )
}
