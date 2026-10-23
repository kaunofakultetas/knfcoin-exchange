// -----------------------------------------------------------
//  [*] Tests — Order page: the countdown, and what replaces it
//
//  On the payment card, while the deposit is awaited: the
//  time left until the order expires — minutes and seconds,
//  ticking every second, amber in its last five minutes,
//  resting at 00:00 since the backend decides the expiry —
//  and, once the deposit is seen, the payment card gone and
//  the status card telling what became of the deposit
//  instead: received (time no longer runs), not received in
//  time, or received on an order that failed. The clock is
//  frozen at the fixtures' moment, when the awaited order has
//  25 minutes left.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { settle } from '../../support/backend/contract'
import { card, orderAnswer, renderOrder } from '../../support/order/page'
import * as f from '../../support/backend/fixtures'


const main = () => screen.getByRole('main')

// The page with its order in, the clock (and the intervals
// that read it) frozen at the fixtures' moment
const renderAt = async (id, now = f.NOW) => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  vi.setSystemTime(now)
  const view = renderOrder(id)
  await within(main()).findByRole('heading', { level: 1, name: `Order #${id}` })
  return view
}

const tick = async (ms) => {
  await act(async () => { vi.advanceTimersByTime(ms) })
}

// The countdown: the figure under "Time remaining"
const countdown = () => within(main()).getByText('Time remaining').nextElementSibling

// The status card's headline, and what it says once the deposit is seen
const headline = () => within(card('Order status')).getByRole('heading', { level: 2 }).textContent
const NO_TIME_LIMIT = /No time limit any more — the swap completes automatically/







// -----------------------------------------------------------
// While the deposit is awaited
// -----------------------------------------------------------
//
// The time left until the order expires: ticking every
// second, amber in its last five minutes, at rest at 00:00
// once the deadline has passed.
// -----------------------------------------------------------

describe('Order countdown — while the deposit is awaited', () => {

  it('shows the time left, in minutes and seconds', async () => {
    await renderAt(f.AWAITING_ID)
    expect(countdown()).toHaveTextContent(/^25:00$/)
  })


  it('ticks every second', async () => {
    await renderAt(f.AWAITING_ID)

    await tick(1000)
    expect(countdown()).toHaveTextContent(/^24:59$/)

    await tick(59000)
    expect(countdown()).toHaveTextContent(/^24:00$/)
  })


  it('turns amber in its last five minutes', async () => {
    await renderAt(f.AWAITING_ID, f.NOW + 20 * 60 * 1000)
    expect(countdown()).toHaveTextContent(/^05:00$/)
    expect(countdown()).not.toHaveClass('text-amber-300')

    await tick(1000)
    expect(countdown()).toHaveTextContent(/^04:59$/)
    expect(countdown()).toHaveClass('text-amber-300')
  })


  it('rests at 00:00 once the deadline passed — the backend decides the expiry', async () => {
    await renderAt(f.AWAITING_ID, f.NOW + 24 * 60 * 1000)

    await tick(2 * 60 * 1000)
    await settle()

    expect(countdown()).toHaveTextContent(/^00:00$/)
    expect(within(main()).getAllByText('Awaiting deposit').length).toBeGreaterThan(0)
  })


  it('shows the minutes past an hour as they are', async () => {
    orderAnswer(f.AWAITING_ID, { expires_at: f.NOW + 90 * 60 * 1000 + 5000 })
    await renderAt(f.AWAITING_ID)
    expect(countdown()).toHaveTextContent(/^90:05$/)
  })
})







// -----------------------------------------------------------
// Once the deposit was seen
// -----------------------------------------------------------
//
// The countdown makes way for what the status card tells:
// received, not received in time, or received on a failed
// order.
// -----------------------------------------------------------

describe('Order countdown — once the deposit was seen', () => {

  it('makes way for the deposit received, and the word that time no longer runs', async () => {
    await renderAt(f.CONFIRMING_ID)
    expect(within(main()).queryByText('Time remaining')).toBeNull()
    expect(headline()).toBe('Confirming your deposit')
    expect(within(card('Order status')).getByText(NO_TIME_LIMIT)).toBeInTheDocument()
  })


  it('goes as soon as a poll brings the deposit', async () => {
    given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, [
      { body: f.orderById(f.AWAITING_ID) },
      { body: { ...f.orderById(f.AWAITING_ID), status: 'awaiting_confirmations', received_amount: 10, tx_deposit_id: 'ab'.repeat(32) } },
    ])
    await renderAt(f.AWAITING_ID)
    expect(countdown()).toHaveTextContent(/^25:00$/)

    await tick(2000)

    expect(await within(main()).findByText('Confirming your deposit')).toBeInTheDocument()
    expect(within(main()).queryByText('Time remaining')).toBeNull()
  })


  it('an expired order says nothing arrived before the deadline — and runs no time', async () => {
    await renderAt(f.EXPIRED_ID)
    expect(headline()).toBe('Order expired')
    expect(within(card('Order status')).getByText(/^Nothing arrived before the deadline\./)).toBeInTheDocument()
    expect(within(main()).queryByText('Time remaining')).toBeNull()
    expect(within(main()).queryByText(NO_TIME_LIMIT)).toBeNull()
  })


  it('a failed order says it failed, without the word that the swap completes', async () => {
    await renderAt(f.FAILED_ID)
    expect(headline()).toBe('Order failed')
    expect(within(main()).queryByText(NO_TIME_LIMIT)).toBeNull()
  })
})
