// -----------------------------------------------------------
//  [*] Tests — Order page: watching the order move
//
//  The page asks for its order every two seconds, so the
//  student watches it go through the pipeline. A poll that
//  fails once the order has loaded keeps the last known state
//  on screen with a note that the connection is being retried
//  — the note goes when a poll gets through again — while an
//  order that never loaded shows the not-found card until a
//  poll finds it. Leaving the page stops the polling, and a
//  late answer about the order the student left — or a late
//  failure — never lands on the next one.
//
//  Only the intervals are faked: the answers still travel
//  through msw on real timers.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { http, HttpResponse, delay } from 'msw'
import { renderApp } from '../../support/render'
import { given, server, url } from '../../support/backend/server'
import { settle } from '../../support/backend/contract'
import { navigateTo } from '../../support/shell/router'
import { watchRequests } from '../../support/shell/requests'
import { progressSteps, renderOrder } from '../../support/order/page'
import * as f from '../../support/backend/fixtures'


const RECONNECTING = 'Connection lost — retrying... The data below may be a few seconds old.'

const main = () => screen.getByRole('main')
const titled = (id) => within(main()).findByRole('heading', { level: 1, name: `Order #${id}` })

// The status in the title row
const status = () => within(main()).getByRole('heading', { level: 1 }).parentElement.nextElementSibling.textContent

const poll = async (times = 1) => {
  await act(async () => { vi.advanceTimersByTime(2000 * times) })
  await settle(50)
}

const fakeIntervals = () => vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })

// The awaited order as later polls find it
const confirming = () => ({ ...f.orderById(f.AWAITING_ID), status: 'awaiting_confirmations', received_amount: 10, confirm_count: 1, tx_deposit_id: 'ab'.repeat(32) })







// -----------------------------------------------------------
// Polling
// -----------------------------------------------------------
//
// The order read again every two seconds: a failed poll keeps
// the last state under a reconnecting note, and nothing is
// asked — or shown — once the student has left.
// -----------------------------------------------------------

describe('Order polling', () => {

  it('asks again every two seconds, and shows how the order moved', async () => {
    fakeIntervals()
    given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, [{ body: f.orderById(f.AWAITING_ID) }, { body: confirming() }])
    const seen = watchRequests()
    renderOrder(f.AWAITING_ID)
    await titled(f.AWAITING_ID)
    expect(status()).toBe('Awaiting deposit')

    await poll()

    expect(status()).toBe('Confirming')
    expect(progressSteps().find((step) => step.current).note).toBe('1 of 2')
    expect(seen).toEqual([`GET /api/exchange/orders/${f.AWAITING_ID}`, `GET /api/exchange/orders/${f.AWAITING_ID}`])
  })


  it('a failed poll keeps the order on screen, with a note that the connection is being retried', async () => {
    fakeIntervals()
    given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, [{ body: f.orderById(f.AWAITING_ID) }, { error: true }])
    renderOrder(f.AWAITING_ID)
    await titled(f.AWAITING_ID)

    await poll()

    expect(within(main()).getByText(RECONNECTING)).toBeInTheDocument()
    expect(within(main()).getByRole('heading', { level: 1, name: `Order #${f.AWAITING_ID}` })).toBeInTheDocument()
    expect(within(main()).getByText(f.orderById(f.AWAITING_ID).deposit_address)).toBeInTheDocument()
  })


  it('the note goes once a poll gets through again', async () => {
    fakeIntervals()
    given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, [
      { body: f.orderById(f.AWAITING_ID) },
      { status: 502, html: '<html><body><h1>502 Bad Gateway</h1></body></html>' },
      { body: confirming() },
    ])
    renderOrder(f.AWAITING_ID)
    await titled(f.AWAITING_ID)
    await poll()
    expect(within(main()).getByText(RECONNECTING)).toBeInTheDocument()

    await poll()

    expect(within(main()).queryByText(RECONNECTING)).toBeNull()
    expect(status()).toBe('Confirming')
  })


  it('an order that never loaded shows the not-found card — until a later poll finds it', async () => {
    fakeIntervals()
    given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, [
      { status: 500, body: { error: 'Internal server error' } },
      { body: f.orderById(f.AWAITING_ID) },
    ])
    renderOrder(f.AWAITING_ID)
    expect(await within(main()).findByRole('heading', { level: 1, name: 'Order not found' })).toBeInTheDocument()

    await poll()

    expect(await titled(f.AWAITING_ID)).toBeInTheDocument()
    expect(within(main()).queryByText('Internal server error')).toBeNull()
    expect(within(main()).queryByText(RECONNECTING)).toBeNull()
  })


  it('asks nothing more once the student has left', async () => {
    fakeIntervals()
    const seen = watchRequests()
    const { unmount } = renderOrder(f.AWAITING_ID)
    await titled(f.AWAITING_ID)

    unmount()
    await poll(5)

    expect(seen).toHaveLength(1)
  })


  it('a late answer about the order the student left never lands on the next one', async () => {
    // The first order's answer is slow; the student moves on to
    // another order before it arrives
    server.use(http.get(url(`/api/exchange/orders/${f.EXPIRED_ID}`), async () => {
      await delay(150)
      return HttpResponse.json(f.orderById(f.EXPIRED_ID))
    }))
    renderApp({ route: `/exchange/order/${f.EXPIRED_ID}` })
    expect(await within(main()).findByText('Loading order...')).toBeInTheDocument()

    await navigateTo(`/exchange/order/${f.COMPLETED_ID}`)
    await titled(f.COMPLETED_ID)
    await act(async () => { await delay(300) })

    expect(within(main()).getByRole('heading', { level: 1, name: `Order #${f.COMPLETED_ID}` })).toBeInTheDocument()
    expect(status()).toBe('Completed')
  })


  it('a late failure about the order the student left raises no alarm on the next one', async () => {
    server.use(http.get(url(`/api/exchange/orders/${f.EXPIRED_ID}`), async () => {
      await delay(150)
      return HttpResponse.json({ error: 'Internal server error' }, { status: 500 })
    }))
    renderApp({ route: `/exchange/order/${f.EXPIRED_ID}` })
    expect(await within(main()).findByText('Loading order...')).toBeInTheDocument()

    await navigateTo(`/exchange/order/${f.COMPLETED_ID}`)
    await titled(f.COMPLETED_ID)
    await act(async () => { await delay(300) })

    expect(within(main()).queryByText(RECONNECTING)).toBeNull()
    expect(within(main()).queryByText('Internal server error')).toBeNull()
  })
})
