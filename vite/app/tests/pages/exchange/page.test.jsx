// -----------------------------------------------------------
//  [*] Tests — Exchange page (/exchange): the page as a whole
//
//  The frame around the swap form and the order list: the
//  title, the two reads it makes on arrival (the live rates
//  and the five latest orders, nothing else), the rates polled
//  every 15 seconds so a long-lived tab stays current — a
//  failed poll keeping the last rates — while the order list
//  is read once, and nothing asked after the student leaves.
//  Then the backend contract of both GETs as this page
//  consumes them. (The form and the list have files of their
//  own.)
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { describeEndpointContract, settle } from '../../support/backend/contract'
import { watchRequests } from '../../support/shell/requests'
import { RATE_LINE, orderRows, panel, recentOrders, renderExchange, submitButton } from '../../support/exchange/page'
import * as f from '../../support/backend/fixtures'


const pageHeading = () => screen.getByRole('heading', { level: 1, name: 'Swap testnet coins' })

// Every request of a kind the watcher saw
const count = (seen, request) => seen.filter((entry) => entry === request).length

const advance = async (ms) => {
  await act(async () => { vi.advanceTimersByTime(ms) })
  await settle(50)
}







// -----------------------------------------------------------
// The page
// -----------------------------------------------------------
//
// The frame around the form and the list: the title, and the
// two reads the page makes on arrival.
// -----------------------------------------------------------

describe('Exchange page', () => {

  it('titles the page and says what is traded, above the form and the order list', async () => {
    renderExchange()
    expect(pageHeading()).toBeInTheDocument()
    expect(screen.getByText('Exchange KNF Coin and Litecoin Testnet4 — settled fully on-chain.')).toBeInTheDocument()
    expect(submitButton()).toBeInTheDocument()
    expect(within(recentOrders()).getByRole('heading', { level: 2, name: 'Recent orders' })).toBeInTheDocument()
    await screen.findByText(RATE_LINE)
  })


  it('asks for the rates and for the five latest orders on arrival — nothing else', async () => {
    const list = given.capture('get', '/api/exchange/orders', f.orders().slice(0, 5))
    const seen = watchRequests()
    renderExchange()

    await screen.findByText(RATE_LINE)
    await settle(100)

    expect([...seen].sort()).toEqual(['GET /api/exchange/orders', 'GET /api/exchange/rates'])
    expect(list.map((call) => call.query)).toEqual([{ limit: '5' }])
  })
})







// -----------------------------------------------------------
// Keeping current
// -----------------------------------------------------------
//
// Only the intervals are faked: the answers still travel
// through msw on real timers.
// -----------------------------------------------------------

describe('Exchange page — keeping current', () => {

  it('polls the rates every 15 seconds — a new rate reaches the quote', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    given.sequence('get', '/api/exchange/rates', [
      { body: f.rates },
      { body: { ...f.rates, pairs: { ...f.rates.pairs, 'KNF Coin->LTC Testnet': 0.125 } } },
    ])
    renderExchange()
    expect(await screen.findByText(RATE_LINE)).toBeInTheDocument()

    await advance(14999)
    expect(screen.getByText(RATE_LINE)).toBeInTheDocument()

    await advance(1)
    expect(await screen.findByText('1 KNF ≈ 0.125 tLTC4')).toBeInTheDocument()
  })


  it('a failed poll keeps the last rates on screen', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    given.sequence('get', '/api/exchange/rates', [
      { body: f.rates },
      { status: 500, body: { error: 'Internal server error' } },
    ])
    const seen = watchRequests()
    renderExchange()
    await screen.findByText(RATE_LINE)

    await advance(15000)

    expect(count(seen, 'GET /api/exchange/rates')).toBe(2)
    expect(screen.getByText(RATE_LINE)).toBeInTheDocument()
    expect(within(panel('You receive')).queryByText('Rate unavailable')).toBeNull()
  })


  it('reads the order list once — it is not polled', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const seen = watchRequests()
    renderExchange()
    await screen.findByText(RATE_LINE)

    await advance(60000)

    expect(count(seen, 'GET /api/exchange/rates')).toBe(5)
    expect(count(seen, 'GET /api/exchange/orders')).toBe(1)
  })


  it('asks nothing more once the student has left', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const seen = watchRequests()
    const { unmount } = renderExchange()
    await screen.findByText(RATE_LINE)
    await settle(50)

    unmount()
    await advance(60000)

    expect(seen).toHaveLength(2)
  })
})







// -----------------------------------------------------------
// Backend contract — GET /api/exchange/rates on the form
// -----------------------------------------------------------
//
// Loaded: the rate line under the estimate and the limits
// under the amount. A failure — and the wait for an answer —
// look the same: the rate unavailable, the limits still
// loading (the next poll may bring them). Whatever the body:
// no crash, the form stands.
// -----------------------------------------------------------

describeEndpointContract({
  path: '/api/exchange/rates',
  fixture: f.rates,
  render: () => renderExchange(),
  chrome: () => pageHeading() && submitButton(),
  loaded: async () => {
    expect(await screen.findByText(RATE_LINE)).toBeInTheDocument()
    const { min, max } = f.rates.limits[f.KNF]
    expect(within(panel('You send')).getByText(`Min ${min} · Max ${max} KNF`)).toBeInTheDocument()
  },
  failed: async () => {
    await settle(50)
    expect(within(panel('You receive')).getByText('Rate unavailable')).toBeInTheDocument()
    expect(within(panel('You send')).getByText('Loading limits...')).toBeInTheDocument()
  },
  loading: () => within(panel('You receive')).queryByText('Rate unavailable') && within(panel('You send')).queryByText('Loading limits...'),
})







// -----------------------------------------------------------
// Backend contract — GET /api/exchange/orders on the list
// -----------------------------------------------------------
//
// Loaded: a row per order. A failure: no rows — never stale
// or invented ones — and the list says it could not be read,
// in the words of the failure. While the answer is awaited:
// the list says it is loading. Whatever the body: no crash,
// the list's heading stands — rows without their id included.
// -----------------------------------------------------------

describeEndpointContract({
  path: '/api/exchange/orders',
  fixture: f.orders().slice(0, 5),
  render: () => renderExchange(),
  chrome: () => within(recentOrders()).getByRole('heading', { level: 2, name: 'Recent orders' }),
  loaded: async () => {
    expect(await within(recentOrders()).findAllByRole('link')).toHaveLength(5)
  },
  failed: async (says) => {
    await settle(50)
    expect(orderRows()).toEqual([])
    expect(within(recentOrders()).getByText(`Could not load your recent orders: ${says}`)).toBeInTheDocument()
  },
  loading: () => within(recentOrders()).queryByText('Loading orders...'),
})
