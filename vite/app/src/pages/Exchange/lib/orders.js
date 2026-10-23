// -----------------------------------------------------------
//  [*] orders — the statuses an order goes through
//
//  The backend is the single source of truth for orders, so
//  there is no client-side storage here anymore - just the set
//  of status strings the backend can return, shared by the
//  Exchange and Order pages for rendering, and the rules both
//  pages read an order by: whether it holds coins the student
//  sent, whether its coins go back instead of being exchanged,
//  whether its address still takes coins to exchange, and the
//  status it is shown with — done as soon as its payout is
//  out, the way a real exchange shows a withdrawal.
//
//  These MUST stay in sync with the statuses written in
//  backend/app/service.py and backend/app/worker.py.
// -----------------------------------------------------------







// -----------------------------------------------------------
// ORDER_STATUS
// -----------------------------------------------------------
//
// The ten status strings the backend writes, by name: five
// while an order moves, five that end it — one of those,
// reversed, ending a completed order once the chain took back
// the deposit its payout was paid for. The pages compare an
// order's status with these, never with bare strings.
//
// Used by:
//   - Order.jsx — the timeline and the summary
//   - components/StatusBadge.jsx — the look of each status
//   - hasReceivedCoins, sendsCoinsBack, takesCoins (below)
// -----------------------------------------------------------

export const ORDER_STATUS = {
  AWAITING_DEPOSIT:       'awaiting_deposit',
  AWAITING_CONFIRMATIONS: 'awaiting_confirmations',
  EXCHANGING:             'exchanging',
  SENDING:                'sending',
  REFUNDING:              'refunding', // could not go through: its coins on their way back
  COMPLETED:              'completed',
  EXPIRED:                'expired',   // nothing received before the deadline
  REFUNDED:               'refunded',  // could not go through: its coins went back
  FAILED:                 'failed',    // could not go through, and its coins could not go back
  REVERSED:               'reversed',  // paid out, then a reorganisation took its deposit back
}







// -----------------------------------------------------------
// hasReceivedCoins
// -----------------------------------------------------------
//
// Whether an order's received amount stands for coins the
// student really sent. An order waiting for its deposit - for
// the first time, or again after the deposit left the chain -
// and an expired one have none, whatever amount they may
// still carry: orders the backend sent back before it learned
// to clear the amount keep a stale one in the database. The
// pages then show the agreed amount, still to be sent.
//
// Used by:
//   - Exchange.jsx — RecentOrders
//   - Order.jsx — the summary and the mismatch note
// -----------------------------------------------------------

export function hasReceivedCoins(order) {
  if (order.status === ORDER_STATUS.AWAITING_DEPOSIT || order.status === ORDER_STATUS.EXPIRED) return false
  return order.receivedAmount > 0
}







// -----------------------------------------------------------
// sendsCoinsBack
// -----------------------------------------------------------
//
// Whether an order does not go through but sends the coins it
// received back to where they came from — refunding, or
// refunded already. The pages then show what goes back
// instead of what would have been received.
//
// Used by:
//   - Exchange.jsx — RecentOrders
//   - Order.jsx — the summary, the timeline and the notes
// -----------------------------------------------------------

export function sendsCoinsBack(order) {
  return order.status === ORDER_STATUS.REFUNDING || order.status === ORDER_STATUS.REFUNDED
}







// -----------------------------------------------------------
// takesCoins
// -----------------------------------------------------------
//
// Whether coins sent to an order's deposit address now would
// still be exchanged: until its rate is locked they are added
// to the deposit. Once it is locked — and once the order has
// ended — they are not: the backend sends coins that arrive
// after the lock back to where they came from, so the page no
// longer offers the address to pay.
//
// Used by:
//   - Order.jsx — the QR code and the note under the address
// -----------------------------------------------------------

export function takesCoins(order) {
  return [ORDER_STATUS.AWAITING_DEPOSIT, ORDER_STATUS.AWAITING_CONFIRMATIONS, ORDER_STATUS.EXCHANGING].includes(order.status)
}







// -----------------------------------------------------------
// payoutConfirming
// -----------------------------------------------------------
//
// Whether an order's payout is out and only its confirmations
// are still to come: the order is sending, its payout has a
// transaction id, and no failure is on record (the backend
// clears one as soon as it sees the payout on its way). No
// real exchange keeps its customer waiting for a payout to
// confirm, so the pages show such an order as done — while
// the backend keeps following the payout until it has
// confirmed, broadcasting it again should the network lose
// it.
//
// Used by:
//   - shownStatus (below)
//   - Order.jsx — the note on the status card
// -----------------------------------------------------------

export function payoutConfirming(order) {
  return order.status === ORDER_STATUS.SENDING && Boolean(order.txSendId) && !order.error
}







// -----------------------------------------------------------
// shownStatus
// -----------------------------------------------------------
//
// The status the pages show an order with: its own, but
// completed for an order whose payout is out and confirming
// (see payoutConfirming).
//
// Used by:
//   - Exchange.jsx — RecentOrders
//   - Order.jsx — the page and every card on it
// -----------------------------------------------------------

export function shownStatus(order) {
  return payoutConfirming(order) ? ORDER_STATUS.COMPLETED : order.status
}
