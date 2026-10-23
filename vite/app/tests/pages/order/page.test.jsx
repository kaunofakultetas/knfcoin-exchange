// -----------------------------------------------------------
//  [*] Tests — Order page (/exchange/order/:orderId): arriving
//      and leaving
//
//  The page around an order: the loading state until the
//  order arrives, the request for the id in the path, the
//  title row — the id, the status, the creation time in the
//  student's own time zone — and the cards under it, one
//  column with the swap on top; the way back to the exchange,
//  an arrow alone on the title's left; the card that replaces
//  the page when the order cannot be shown (unknown to the
//  backend, or a failure before it ever loaded — in the words
//  that came back, the page's own sentence when none came),
//  with its own way back; then the backend contract of GET
//  /api/exchange/orders/<id> as this page consumes it — for
//  an order that went through and for one whose coins go
//  back, its refunds broken every way the matrix breaks an
//  answer. (What the page says about the swap, its countdown,
//  timeline and polling have files of their own.)
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { describeEndpointContract, settle } from '../../support/backend/contract'
import { currentPath } from '../../support/shell/router'
import { renderOrder } from '../../support/order/page'
import * as f from '../../support/backend/fixtures'
import { ExchangeApi } from '@/pages/Exchange/lib/api.js'


const main = () => screen.getByRole('main')
const titled = (id) => within(main()).findByRole('heading', { level: 1, name: `Order #${id}` })

// The title row: the heading and what sits beside it
const titleRow = () => within(main()).getByRole('heading', { level: 1 }).parentElement.parentElement

// The frame every state of the page keeps
const chrome = () => screen.getByRole('navigation') && screen.getByRole('contentinfo')

const precedes = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)







// -----------------------------------------------------------
// Arriving
// -----------------------------------------------------------
//
// The page while it loads and once the order is there: the
// order its path names, titled with its id, its status and
// its creation time.
// -----------------------------------------------------------

describe('Order page — arriving', () => {

  it('says it is loading until the order arrives — inside the usual frame', async () => {
    given.hang('get', `/api/exchange/orders/${f.AWAITING_ID}`)
    renderOrder(f.AWAITING_ID)
    await settle(100)

    expect(within(main()).getByText('Loading order...')).toBeInTheDocument()
    expect(within(main()).queryByRole('heading')).toBeNull()
    expect(chrome()).toBeTruthy()
  })


  it('asks the backend for the order named in the path', async () => {
    const calls = given.capture('get', '/api/exchange/orders/:orderId', ({ params }) => f.orderById(params.orderId))
    renderOrder(f.EXCHANGING_ID)

    await titled(f.EXCHANGING_ID)
    expect(calls[0].params).toEqual({ orderId: f.EXCHANGING_ID })
  })


  it('titles the page with the id, the status and when the order was created, in local time', async () => {
    vi.stubEnv('TZ', 'Europe/Vilnius')
    renderOrder(f.AWAITING_ID)

    expect(await titled(f.AWAITING_ID)).toBeInTheDocument()
    expect(within(titleRow()).getByText('Created 2026-10-04 12:15:00')).toBeInTheDocument()
    expect(within(titleRow()).getByText('Awaiting deposit')).toBeInTheDocument()
  })


  it('the creation time follows the student\'s time zone', async () => {
    vi.stubEnv('TZ', 'UTC')
    renderOrder(f.AWAITING_ID)

    await titled(f.AWAITING_ID)
    expect(within(titleRow()).getByText('Created 2026-10-04 09:15:00')).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// The cards
// -----------------------------------------------------------
//
// One column of cards under the title row, read top to
// bottom: the swap first — what goes in and what comes out —
// then the status with its steps, then the rest: the payment
// while the deposit is awaited, the coins sent back once any
// went, and the details.
// -----------------------------------------------------------

describe('Order page — the cards', () => {

  it.each([
    ['awaiting_deposit', f.AWAITING_ID, ['Swap', 'Order status', 'Payment', 'Order details']],
    ['completed', f.COMPLETED_ID, ['Swap', 'Order status', 'Order details']],
    ['refunding', f.REFUNDING_ID, ['Swap', 'Order status', 'Coins sent back', 'Order details']],
  ])('%s: the cards read, top to bottom, %j', async (_, id, cards) => {
    renderOrder(id)
    await titled(id)

    expect(within(main()).getAllByRole('region').map((region) => region.getAttribute('aria-label'))).toEqual(cards)
  })
})







// -----------------------------------------------------------
// An order that cannot be shown
// -----------------------------------------------------------
//
// The not-found card: an unknown id, or a failure before the
// order ever loaded — with what went wrong.
// -----------------------------------------------------------

describe('Order page — an order that cannot be shown', () => {

  it('an id the backend does not know: "Order not found", its sentence, and the way back', async () => {
    renderOrder('NOPE1234')

    expect(await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })).toBeInTheDocument()
    expect(within(main()).getByText('Not found')).toBeInTheDocument()
    expect(within(main()).getByRole('link', { name: 'Back to Exchange' })).toHaveAttribute('href', '/exchange')
  })


  it('a failure before the order ever loaded shows the same card, with what went wrong', async () => {
    given.error('get', `/api/exchange/orders/${f.AWAITING_ID}`, 'Internal server error', 500)
    renderOrder(f.AWAITING_ID)

    expect(await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })).toBeInTheDocument()
    expect(within(main()).getByText('Internal server error')).toBeInTheDocument()
  })


  it('a failure that comes without words falls back to the page\'s own sentence', async () => {
    // No answer of the backend makes ExchangeApi fail without
    // naming a reason, so ExchangeApi itself fails silently here
    vi.spyOn(ExchangeApi, 'getOrder').mockRejectedValue(new Error(''))
    renderOrder(f.AWAITING_ID)

    expect(await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })).toBeInTheDocument()
    expect(within(main()).getByText('Failed to load order')).toBeInTheDocument()
  })


  it('an empty answer is an order not found, with nothing to add', async () => {
    given.json('get', `/api/exchange/orders/${f.AWAITING_ID}`, null)
    renderOrder(f.AWAITING_ID)

    const heading = await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })
    expect(heading.parentElement.textContent).toBe('Order not foundBack to Exchange')
  })


  it('"Back to Exchange" leads to the exchange inside the app', async () => {
    const { user } = renderOrder('NOPE1234')

    await user.click(await within(main()).findByRole('link', { name: 'Back to Exchange' }))

    expect(currentPath()).toBe('/exchange')
  })
})







// -----------------------------------------------------------
// The way back
// -----------------------------------------------------------
//
// The arrow on the title's left, the page's only way back to
// the exchange: an icon with no words beside it, named for a
// screen reader by where it leads.
// -----------------------------------------------------------

describe('Order page — the way back', () => {

  it('the arrow left of the title leads to the exchange inside the app', async () => {
    const { user } = renderOrder(f.COMPLETED_ID)
    await titled(f.COMPLETED_ID)

    await user.click(within(titleRow()).getByRole('link', { name: 'Back to Exchange' }))

    await waitFor(() => expect(currentPath()).toBe('/exchange'))
  })


  it('is an arrow alone, before the title — and the page\'s only way back', async () => {
    renderOrder(f.COMPLETED_ID)
    const heading = await titled(f.COMPLETED_ID)

    const back = within(main()).getByRole('link', { name: /back to exchange/i })
    expect(back.textContent).toBe('')
    expect(back.querySelector('svg')).not.toBeNull()
    expect(precedes(back, heading)).toBe(true)
  })
})







// -----------------------------------------------------------
// Backend contract — GET /api/exchange/orders/<id>
// -----------------------------------------------------------
//
// Loaded: the order's title. A failure on the first read: the
// "Order not found" card with the words that came back. In
// flight: "Loading order...". Whatever the body: no crash,
// the header and the footer stand — for the completed order,
// and for the one sending its coins back, whose refunds the
// variants break as well.
// -----------------------------------------------------------

for (const id of [f.COMPLETED_ID, f.REFUNDING_ID]) {
  describeEndpointContract({
    path: `/api/exchange/orders/${id}`,
    fixture: f.orderById(id),
    render: () => renderOrder(id),
    chrome,
    loaded: async () => {
      expect(await titled(id)).toBeInTheDocument()
    },
    failed: async (says) => {
      expect(await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })).toBeInTheDocument()
      expect(within(main()).getByText(says)).toBeInTheDocument()
    },
    loading: () => within(main()).queryByText('Loading order...'),
  })
}
