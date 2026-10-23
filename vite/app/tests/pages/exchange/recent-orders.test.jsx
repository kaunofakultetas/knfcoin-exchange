// -----------------------------------------------------------
//  [*] Tests — Exchange page: the recent orders list
//
//  The five latest orders under the form, newest first, each
//  row a link to its order's page: both coins in the order of
//  the swap, what is sent and roughly what is received, the
//  id, how long ago the order was made and the status — done
//  as soon as its payout is out. Once coins have arrived a row shows what
//  was actually deposited rather than the agreed amount, and
//  the received side follows it — exact once the backend
//  locked the rate, estimated from the deposit before; an
//  order back to awaiting its deposit, or expired, shows the
//  agreed amount whatever received amount it still carries,
//  and one whose coins go back says so instead of an
//  estimate.
//  The age is worded from the browser's clock in the largest
//  unit it spans — "just now" under a minute — and kept up
//  every 30 seconds while the page stays open, the exact
//  moment on hover. With no orders, the list says where the swaps will appear;
//  while it loads, that it is loading; when it could not be
//  read, why — never that there are no orders.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { settle } from '../../support/backend/contract'
import { currentPath } from '../../support/shell/router'
import { watchRequests } from '../../support/shell/requests'
import { orderRows, recentOrders, renderExchange } from '../../support/exchange/page'
import * as f from '../../support/backend/fixtures'


const NO_ORDERS = 'No orders yet — your swaps will appear here.'
const LOADING = 'Loading orders...'

// The page with its list in
const renderWithList = async () => {
  const view = renderExchange()
  await within(recentOrders()).findAllByRole('link')
  return view
}

// The list answering with these rows only
const listOf = (...rows) => given.json('get', '/api/exchange/orders', rows)

// The coin logos of a row, in the order shown
const coinsOf = (row) => Array.from(row.querySelectorAll('img'), (logo) => logo.getAttribute('src'))







// -----------------------------------------------------------
// The rows
// -----------------------------------------------------------
//
// Each order of the list as a row: both coins, what was sent
// and roughly what is received, the id and the status — a
// link to the order's page.
// -----------------------------------------------------------

describe('Recent orders', () => {

  it('lists the five latest orders, newest first, each a link to its page', async () => {
    await renderWithList()
    expect(orderRows().map((row) => row.getAttribute('href'))).toEqual([
      `/exchange/order/${f.AWAITING_ID}`,
      `/exchange/order/${f.CONFIRMING_ID}`,
      `/exchange/order/${f.EXCHANGING_ID}`,
      `/exchange/order/${f.REFUNDING_ID}`,
      `/exchange/order/${f.SENDING_ID}`,
    ])
  })


  it('shows each swap with both coins in its order, the amounts, the id and the status', async () => {
    await renderWithList()
    const [awaiting, confirming] = orderRows()

    expect(coinsOf(awaiting)).toEqual([f.ICONS[f.KNF], f.ICONS[f.LTC]])
    expect(awaiting).toHaveTextContent('10 KNF Coin→≈1.2345678 LTC Testnet')
    expect(within(awaiting).getByText(`#${f.AWAITING_ID}`)).toBeInTheDocument()
    expect(within(awaiting).getByText('Awaiting deposit')).toBeInTheDocument()

    expect(coinsOf(confirming)).toEqual([f.ICONS[f.LTC], f.ICONS[f.KNF]])
    expect(confirming).toHaveTextContent('0.5 LTC Testnet→≈4.05000033 KNF Coin')
    expect(within(confirming).getByText('Confirming')).toBeInTheDocument()
  })


  it('an order that received nothing yet shows the agreed amount, and its estimate', async () => {
    await renderWithList()
    expect(orderRows()[0]).toHaveTextContent('10 KNF Coin→≈1.2345678 LTC Testnet')
  })


  it('once coins arrived, shows what was actually deposited — not the agreed amount', async () => {
    await renderWithList()
    const sending = orderRows()[4]
    expect(sending).toHaveTextContent('12.5 KNF Coin→≈1.54320975 LTC Testnet')
    expect(sending).not.toHaveTextContent('10 KNF Coin')
  })


  it('estimates the payout from the deposit until the rate is locked', async () => {
    listOf({ ...f.orderById(f.CONFIRMING_ID), received_amount: 0.6 })
    await renderWithList()
    expect(orderRows()[0]).toHaveTextContent('0.6 LTC Testnet→≈4.8600004 KNF Coin')
  })


  it('shows the exact payout once the rate is locked — not a fresh estimate', async () => {
    listOf({ ...f.orderById(f.SENDING_ID), locked_rate: 0.1, to_amount: 1.25 })
    await renderWithList()
    expect(orderRows()[0]).toHaveTextContent('12.5 KNF Coin→≈1.25 LTC Testnet')
  })


  it.each([
    ['back to awaiting its deposit', 'awaiting_deposit'],
    ['expired', 'expired'],
  ])('an order %s shows the agreed amount, whatever received amount it still carries', async (_, status) => {
    // What an older backend left on an order whose deposit vanished
    listOf({ ...f.orderById(f.AWAITING_ID), status, received_amount: 12.5 })
    await renderWithList()
    expect(orderRows()[0]).toHaveTextContent('10 KNF Coin→≈1.2345678 LTC Testnet')
  })


  it.each([
    ['on their way back', f.REFUNDING_ID, '1,500 KNF Coin→sent back', 'Refunding'],
    ['already back', f.REFUNDED_ID, '0.00003 KNF Coin→sent back', 'Refunded'],
  ])('an order whose coins are %s says they are sent back, not what it would have paid', async (_, id, text, badge) => {
    listOf(f.orderById(id))
    await renderWithList()
    expect(orderRows()[0]).toHaveTextContent(text)
    expect(orderRows()[0]).not.toHaveTextContent('LTC Testnet')
    expect(within(orderRows()[0]).getByText(badge)).toBeInTheDocument()
  })


  it('an order whose payout is out wears "Completed" while the payout confirms', async () => {
    listOf({ ...f.orderById(f.SENDING_ID), error: null, tx_send_id: f.PAYOUT_TXID })
    await renderWithList()
    expect(within(orderRows()[0]).getByText('Completed')).toBeInTheDocument()
  })


  it('shows a status the frontend does not know as the backend wrote it', async () => {
    listOf({ ...f.orderById(f.COMPLETED_ID), status: 'cancelled' })
    await renderWithList()
    expect(within(orderRows()[0]).getByText('cancelled')).toBeInTheDocument()
  })


  it('a click on a row opens that order inside the app', async () => {
    const { user } = await renderWithList()
    await user.click(orderRows()[4])
    expect(currentPath()).toBe(`/exchange/order/${f.SENDING_ID}`)
  })
})







// -----------------------------------------------------------
// How long ago
// -----------------------------------------------------------
//
// Each row tells how long ago its order was made, from the
// browser's clock frozen at the fixtures' classroom morning;
// only the intervals and the clock are faked, the answers
// still travel through msw on real timers.
// -----------------------------------------------------------

describe('Recent orders — how long ago', () => {

  const MINUTE = 60 * 1000
  const DAY = 24 * 60 * MINUTE

  // The page with its list in, the clock frozen at `moment`
  const renderAt = async (moment) => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
    vi.setSystemTime(moment)
    return renderWithList()
  }

  // The age a row tells — its time element, when it has one
  const ageOf = (row) => row.querySelector('time')

  // The list answering with the awaiting order made `age` before NOW
  const madeAgo = (age) => listOf({ ...f.orderById(f.AWAITING_ID), created_at: f.NOW - age })


  it('tells how long ago each order was made', async () => {
    await renderAt(f.NOW)
    expect(orderRows().map((row) => ageOf(row).textContent)).toEqual([
      '5 minutes ago', '15 minutes ago', '30 minutes ago', '40 minutes ago', '50 minutes ago',
    ])
  })


  it('beside the id, after a dot no screen reader reads out', async () => {
    await renderAt(f.NOW)
    const id = within(orderRows()[0]).getByText(`#${f.AWAITING_ID}`)
    expect(id.nextElementSibling).toHaveTextContent(/^·$/)
    expect(id.nextElementSibling).toHaveAttribute('aria-hidden', 'true')
    expect(id.nextElementSibling.nextElementSibling).toBe(ageOf(orderRows()[0]))
  })


  it('carries the exact moment in its datetime, and shows it on hover', async () => {
    await renderAt(f.NOW)
    const age = ageOf(orderRows()[0])
    expect(age).toHaveAttribute('datetime', '2026-10-04T09:15:00.000Z')
    expect(age).toHaveAttribute('title', new Date(1791105300000).toLocaleString())
  })


  it('keeps up while the page stays open — worded anew every 30 seconds, the list never read again', async () => {
    const seen = watchRequests()
    await renderAt(f.NOW)

    await act(async () => { vi.advanceTimersByTime(2 * MINUTE) })
    await settle(50)

    expect(ageOf(orderRows()[0])).toHaveTextContent(/^7 minutes ago$/)
    expect(seen.filter((request) => request === 'GET /api/exchange/orders')).toHaveLength(1)
  })


  it.each([
    [0, 'just now'],
    [59 * 1000, 'just now'],
    [MINUTE, '1 minute ago'],
    [2 * MINUTE - 1, '1 minute ago'],
    [61 * MINUTE, '1 hour ago'],
    [25 * 60 * MINUTE, '1 day ago'],
    [6 * DAY, '6 days ago'],
    [8 * DAY, '1 week ago'],
    [45 * DAY, '1 month ago'],
    [400 * DAY, '1 year ago'],
    [3 * 365 * DAY, '3 years ago'],
  ])('an order made %i ms ago reads "%s"', async (age, words) => {
    madeAgo(age)
    await renderAt(f.NOW)
    expect(ageOf(orderRows()[0])).toHaveTextContent(new RegExp(`^${words}$`))
  })


  it('an order the browser\'s clock has not reached yet was made just now', async () => {
    madeAgo(-5 * MINUTE)
    await renderAt(f.NOW)
    expect(ageOf(orderRows()[0])).toHaveTextContent(/^just now$/)
  })


  it.each([null, 'yesterday', 1e20])('a creation time of %j tells no age — the row still stands', async (created) => {
    listOf({ ...f.orderById(f.AWAITING_ID), created_at: created })
    await renderAt(f.NOW)
    expect(ageOf(orderRows()[0])).toBeNull()
    expect(within(orderRows()[0]).getByText(`#${f.AWAITING_ID}`)).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// No rows
// -----------------------------------------------------------
//
// An empty list, a list on its way and a list that could not
// be read each say what they are: only the first claims there
// are no orders.
// -----------------------------------------------------------

describe('Recent orders — no rows', () => {

  it('with no orders yet, says where the swaps will appear', async () => {
    listOf()
    renderExchange()
    await settle(100)
    expect(within(recentOrders()).getByText(NO_ORDERS)).toBeInTheDocument()
    expect(orderRows()).toEqual([])
  })


  it('while the list is on its way, says it is loading — not that there are none', async () => {
    given.hang('get', '/api/exchange/orders')
    renderExchange()
    await settle(100)
    expect(within(recentOrders()).getByText(LOADING)).toBeInTheDocument()
    expect(within(recentOrders()).queryByText(NO_ORDERS)).toBeNull()
  })


  it('a list that could not be loaded says why, and does not claim there are no orders', async () => {
    given.error('get', '/api/exchange/orders', 'Internal server error', 500)
    renderExchange()
    await settle(100)
    expect(within(recentOrders()).getByText('Could not load your recent orders: Internal server error')).toBeInTheDocument()
    expect(within(recentOrders()).queryByText(NO_ORDERS)).toBeNull()
    expect(within(recentOrders()).queryByText(LOADING)).toBeNull()
  })


  it('shows no rows when the list fails — nothing stale, nothing invented', async () => {
    given.networkError('get', '/api/exchange/orders')
    renderExchange()
    await settle(100)
    expect(orderRows()).toEqual([])
    expect(screen.getByRole('heading', { level: 2, name: 'Recent orders' })).toBeInTheDocument()
  })
})
