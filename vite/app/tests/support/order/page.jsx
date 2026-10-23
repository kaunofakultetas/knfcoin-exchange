// -----------------------------------------------------------
//  [*] Test support — the Order page, as a student reads it
//
//  The order page's cards are named regions, its steps an
//  "Order progress" list and its QR code an image named for
//  what it encodes; the six Order test files share these
//  handles on it:
//
//    renderOrder   — the page for an order id, mounted on its
//                    route with the location probe beside it
//    orderAnswer   — the default handler's row of an order,
//                    edited, as the answer for its id
//    card          — one of the page's cards, by its name
//    progressSteps — each step's mark (a tick, the spinner of
//                    the current step as an empty mark, its
//                    number ahead, where an order stopped "!"
//                    or "✕"), label, whether it is the current
//                    step, and the note under it — the
//                    pipeline's steps, or the refund's
//    qrCodes / qrCode / qrFor — the QR codes on the page, the
//                    one there is, and the one a value
//                    encodes, to compare their modules
//
//  Used by:
//    - pages/order/*.test.jsx
// -----------------------------------------------------------

import { render, screen, within } from '@testing-library/react'
import { Route, Routes } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { renderPage } from '../render'
import { given } from '../backend/server'
import { LocationProbe } from '../shell/router'
import * as f from '../backend/fixtures'
import Order from '@/pages/Exchange/Order.jsx'







// -----------------------------------------------------------
// renderOrder
// -----------------------------------------------------------
//
// The page for an order id inside renderPage's memory router,
// on the route pattern App.jsx gives it so useParams reads
// the id — with the location probe outside that route, so it
// still reports where the student went after the page itself
// has unmounted.
//
// Used by:
//   - the Order test files
// -----------------------------------------------------------

export const renderOrder = (id) => renderPage(
  <>
    <Routes>
      <Route path="/exchange/order/:orderId" element={<Order />} />
    </Routes>
    <LocationProbe />
  </>,
  { route: `/exchange/order/${encodeURIComponent(id)}` },
)







// -----------------------------------------------------------
// orderAnswer
// -----------------------------------------------------------
//
// Answers GET /api/exchange/orders/<id> with the fixture row
// of that id, the given columns changed — the way a test
// reads one variation of an order without touching the
// shared fixture. Returns the row it answers with.
//
// Used by:
//   - the Order test files
// -----------------------------------------------------------

export function orderAnswer(id, changes = {}) {
  const row = { ...f.orderById(id), ...changes }
  given.json('get', `/api/exchange/orders/${id}`, row)
  return row
}







// -----------------------------------------------------------
// card
// -----------------------------------------------------------
//
// One of the page's cards by the name it carries: "Order
// status", "Payment", "Swap", "Coins sent back", "Order
// details".
//
// Used by:
//   - the Order test files
// -----------------------------------------------------------

export const card = (name) => screen.getByRole('region', { name })







// -----------------------------------------------------------
// progressSteps
// -----------------------------------------------------------
//
// The steps of the "Order progress" list, in order: each
// one's mark, its label, whether it is the current step, and
// the note under it (the confirmations, while confirming) or
// null. The labels of the pipeline and of the refund are
// exported beside it.
//
// Used by:
//   - order/timeline.test.jsx, order/reorg.test.jsx,
//     order/polling.test.jsx
// -----------------------------------------------------------

export const STEP_LABELS = ['Deposit', 'Confirming', 'Exchanging', 'Sending', 'Done']
export const REFUND_STEP_LABELS = ['Deposit', 'Confirming', 'Exchanging', 'Sending back', 'Sent back']

export const progressSteps = () => within(screen.getByRole('list', { name: 'Order progress' })).getAllByRole('listitem').map((step) => ({
  mark: step.children[0].textContent,
  label: step.children[1].textContent,
  current: step.getAttribute('aria-current') === 'step',
  note: step.children[2]?.textContent ?? null,
}))







// -----------------------------------------------------------
// qrCodes / qrCode / qrFor
// -----------------------------------------------------------
//
// The QR codes on the page — an image named for the deposit
// address it encodes — the one there is, and the modules a
// QR code of the same size draws for a given value, rendered
// apart from the page; equal modules mean the page's code
// encodes that value.
//
// Used by:
//   - order/summary.test.jsx
// -----------------------------------------------------------

const QR_NAME = 'QR code of the deposit address'

export const qrCodes = () => screen.queryAllByRole('img', { name: QR_NAME })

export const qrCode = () => screen.getByRole('img', { name: QR_NAME }).querySelector('svg')

export const qrFor = (value) => render(<QRCodeSVG value={value} size={168} />, { container: document.createElement('div') })
  .container.querySelector('svg')
