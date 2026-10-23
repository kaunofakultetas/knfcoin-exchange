// -----------------------------------------------------------
//  [*] Test support — the Exchange page, as a student uses it
//
//  The swap form carries no labels a query could take hold of:
//  its amount fields are known by their placeholder, the
//  address field by its hint, each swap panel by the words
//  above it ("You send", "You receive"). The three Exchange
//  test files share these handles on it rather than each
//  inventing its own:
//
//    renderExchange — the page at /exchange, the location probe
//                     beside it to see where a submit leads
//    RATE_LINE      — the KNF → tLTC4 rate as the quote shows it
//    sendField / receiveField / addressField — the inputs
//    panel          — a swap panel, by its label
//    submitButton / flipButton — the form's two buttons
//    fillOrder      — an amount and an address typed, submitted
//    recentOrders / orderRows — the list under the form
//
//  Used by:
//    - pages/exchange/page.test.jsx, swap-form.test.jsx,
//      recent-orders.test.jsx
// -----------------------------------------------------------

import { screen, within } from '@testing-library/react'
import { renderPage } from '../render'
import { regionAround } from '../regions'
import { LocationProbe } from '../shell/router'
import Exchange from '@/pages/Exchange/Exchange.jsx'


// The rate line under the estimate for the default direction
export const RATE_LINE = '1 KNF ≈ 0.12345678 tLTC4'







// -----------------------------------------------------------
// renderExchange
// -----------------------------------------------------------
//
// The page at /exchange inside renderPage's memory router,
// mounted outside any route so it stays when a submit
// navigates — the probe beside it then reports where the
// student was sent.
//
// Used by:
//   - the Exchange test files
// -----------------------------------------------------------

export const renderExchange = () => renderPage(<><Exchange /><LocationProbe /></>, { route: '/exchange' })







// -----------------------------------------------------------
// The form's handles
// -----------------------------------------------------------
//
// The two amount fields share their placeholder: the first is
// the amount sent, the second the read-only estimate. The
// address field is known by its hint, whichever asset it asks
// for. A panel is the nearest element around its label that
// holds an input; the submit button is found by either of its
// two captions.
//
// Used by:
//   - the Exchange test files
// -----------------------------------------------------------

const amountFields = () => screen.getAllByPlaceholderText('0.00000000')

export const sendField = () => amountFields()[0]
export const receiveField = () => amountFields()[1]
export const addressField = () => screen.getByPlaceholderText(/^Your .+ address \((knf|tltc)1\.\.\.\)$/)

export const panel = (label) => regionAround(label, (node) => node.querySelector('input') !== null)

export const submitButton = () => screen.getByRole('button', { name: /^(Exchange now|Creating order\.\.\.)$/ })
export const flipButton = () => screen.getByRole('button', { name: 'Swap direction' })







// -----------------------------------------------------------
// fillOrder
// -----------------------------------------------------------
//
// What a student does to place an order: types the amount and
// the address (either may be left empty) and presses
// "Exchange now".
//
// Used by:
//   - swap-form.test.jsx — the form tests and the POST
//     contract
// -----------------------------------------------------------

export async function fillOrder(user, amount, address) {
  if (amount) await user.type(sendField(), amount)
  if (address) await user.type(addressField(), address)
  await user.click(submitButton())
}







// -----------------------------------------------------------
// recentOrders / orderRows
// -----------------------------------------------------------
//
// The section under its "Recent orders" heading, and its rows
// — one link per order, in the order shown.
//
// Used by:
//   - recent-orders.test.jsx, page.test.jsx — the list
//     contract
// -----------------------------------------------------------

export const recentOrders = () => screen.getByRole('heading', { level: 2, name: 'Recent orders' }).closest('section')

export const orderRows = () => within(recentOrders()).queryAllByRole('link')
