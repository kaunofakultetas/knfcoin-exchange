// -----------------------------------------------------------
//  [*] Tests — Order page: when the chain reorganises
//
//  The page never sees a reorganisation itself: it sees the
//  order the backend reports, poll after poll, and a reorg
//  shows there as an order moving BACKWARDS. These tests
//  replay the answers the backend's order worker gives in each
//  case, and check the page follows them:
//    - the block holding the deposit is orphaned and its
//      transaction falls back into the mempool: the
//      confirmations drop, the order keeps confirming — and
//      one caught at the rate lock goes back to confirming
//    - the deposit vanishes for good (double-spent, or
//      replaced): the order returns to awaiting its deposit —
//      from confirming, or from the rate lock — and the page
//      asks for the deposit again, no longer saying any coins
//      were sent; past the deadline, the countdown comes back
//      at 00:00 and the next answer expires the order
//    - a deposit that turns up again (re-mined, or under the
//      new id of a fee bump) moves the order forward again,
//      even after the order expired
//    - a deposit gone, or back in the mempool, while the
//      payout waited: the locked payout is undone
//    - a deposit the chain took back after the payout: the
//      completed order turns reversed — its deposit struck
//      through, the payout kept — and is complete again once
//      the chain holds the deposit again
//    - a top-up that vanishes before it confirms takes the
//      amounts back down
//
//  When the worker sends an order back it clears the received
//  amount. Orders it sent back before it did so still carry
//  the stale amount in the database, and the page reads that
//  as no coins sent all the same.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { settle } from '../../support/backend/contract'
import { card, progressSteps, renderOrder } from '../../support/order/page'
import { wholeText } from '../../support/regions'
import * as f from '../../support/backend/fixtures'


const RECONNECTING = 'Connection lost — retrying... The data below may be a few seconds old.'
const NO_TIME_LIMIT = /No time limit any more — the swap completes automatically/
const MISMATCH = 'You sent 12.5 KNF Coin instead of the agreed 10 — the payout follows what actually arrived.'

// The awaited order's deposit, as the worker records it at
// first sight, and the id a fee bump gives it
const DEPOSIT_TX = 'ab'.repeat(32)
const BUMPED_TX = 'cd'.repeat(32)

// The worker's records of the awaited order, step by step:
// its 10 KNF seen and confirming, confirmed, the rate locked
// with the payout due, and — after the deposit vanished —
// sent back to awaiting it with nothing received, then
// expired; or paid out, and reversed once the chain took the
// deposit back
const confirming = (changes = {}) => ({
  ...f.orderById(f.AWAITING_ID),
  status: 'awaiting_confirmations',
  received_amount: 10,
  tx_deposit_id: DEPOSIT_TX,
  confirm_count: 1,
  ...changes,
})
const exchanging = () => confirming({ status: 'exchanging', confirm_count: 2 })
const sending = () => confirming({ status: 'sending', confirm_count: 2, locked_rate: 0.125, to_amount: 1.25 })
const sentBack = (changes = {}) => confirming({ status: 'awaiting_deposit', tx_deposit_id: null, confirm_count: 0, received_amount: 0, ...changes })
const completed = (changes = {}) => confirming({ status: 'completed', confirm_count: 2, locked_rate: 0.125, to_amount: 1.25, tx_send_id: 'ef'.repeat(32), ...changes })
const reversed = () => completed({ status: 'reversed' })
const expiredAfterRevert = (changes = {}) => ({ ...sentBack(changes), status: 'expired' })

// What an older backend left on an order it sent back: the
// amount received before the deposit vanished
const STALE = { received_amount: 12.5 }

// Past the order's deadline: NOW is 25 minutes before it
const AFTER_DEADLINE = f.NOW + 30 * 60 * 1000

const main = () => screen.getByRole('main')

// The page for the awaited order with the clock frozen at
// `moment`, its polls answered by `answers` in turn — the last
// one repeating. Only the intervals and the clock are faked:
// the answers still travel through msw on real timers
const renderAt = async (moment, answers) => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval', 'Date'] })
  vi.setSystemTime(moment)
  given.sequence('get', `/api/exchange/orders/${f.AWAITING_ID}`, answers.map((body) => ({ body })))
  const view = renderOrder(f.AWAITING_ID)
  await within(main()).findByRole('heading', { level: 1, name: `Order #${f.AWAITING_ID}` })
  return view
}

const poll = async () => {
  await act(async () => { vi.advanceTimersByTime(2000) })
  await settle(50)
}

// What the page reads: the status in the title row and in the
// status card's headline, the steps' marks, the confirmations
// under the current step, the countdown when it shows, and the
// two halves of the swap
const status = () => within(main()).getByRole('heading', { level: 1 }).parentElement.nextElementSibling.textContent
const headline = () => within(card('Order status')).getByRole('heading', { level: 2 }).textContent
const marks = () => progressSteps().map((step) => step.mark)
const confirmations = () => progressSteps().find((step) => step.current)?.note ?? null
const countdown = () => within(main()).queryByText('Time remaining')?.nextElementSibling ?? null
const sendSide = () => {
  const label = within(main()).getByText(/^You sen[dt]$/)
  return [label.textContent, label.nextElementSibling.textContent]
}
const receiveSide = () => within(main()).getByText('You receive').nextElementSibling.textContent







// -----------------------------------------------------------
// A block orphaned with the deposit in it
// -----------------------------------------------------------
//
// Confirmations taken back by an orphaned block: the order
// keeps confirming, or goes back to it from the rate lock,
// with no alarm raised.
// -----------------------------------------------------------

describe('Order page — a block orphaned with the deposit in it', () => {

  it('takes the confirmations back: the order keeps confirming, its count drops, no alarm is raised', async () => {
    await renderAt(f.NOW, [confirming(), confirming({ confirm_count: 0 })])
    expect(confirmations()).toBe('1 of 2')

    await poll()

    expect(confirmations()).toBe('0 of 2')
    expect(status()).toBe('Confirming')
    expect(headline()).toBe('Confirming your deposit')
    expect(marks()).toEqual(['✓', '', '3', '4', '5'])
    expect(within(main()).queryByText(RECONNECTING)).toBeNull()
  })


  it('caught at the rate lock: the order goes back to confirming, its coins still received', async () => {
    await renderAt(f.NOW, [exchanging(), confirming({ confirm_count: 0 })])
    expect(status()).toBe('Exchanging')

    await poll()

    expect(status()).toBe('Confirming')
    expect(confirmations()).toBe('0 of 2')
    expect(headline()).toBe('Confirming your deposit')
    expect(sendSide()).toEqual(['You sent', '10 KNF Coin'])
  })
})







// -----------------------------------------------------------
// A deposit that vanished
// -----------------------------------------------------------
//
// A deposit double-spent or replaced: the order is back at
// its first step, asking for the deposit with no coins said
// to be sent — and moves on again when a deposit returns.
// -----------------------------------------------------------

describe('Order page — a deposit that vanished', () => {

  it.each([
    ['while it confirmed', confirming],
    ['at the rate lock', exchanging],
  ])('vanished %s: the order is back at its first step, and the page asks for the deposit again', async (_, before) => {
    await renderAt(f.NOW, [before(), sentBack()])
    expect(screen.queryByRole('region', { name: 'Payment' })).toBeNull()

    await poll()

    expect(status()).toBe('Awaiting deposit')
    expect(headline()).toBe('Waiting for your deposit')
    expect(marks()).toEqual(['', '2', '3', '4', '5'])
    expect(confirmations()).toBeNull()
    expect(countdown()).toHaveTextContent(/^24:58$/)
    expect(within(card('Payment')).getByText(wholeText('Send 10 KNF Coin to this address:'))).toBeInTheDocument()
    expect(within(card('Payment')).getByText('Scan to pay 10 KNF Coin')).toBeInTheDocument()
    expect(within(main()).queryByText(NO_TIME_LIMIT)).toBeNull()
  })


  it.each([
    ['as the backend reports it', {}],
    ['with the stale amount an older backend left on it', STALE],
  ])('sent back, it no longer says the coins were sent — %s', async (_, changes) => {
    await renderAt(f.NOW, [confirming(STALE), sentBack(changes)])

    await poll()

    expect(sendSide()).toEqual(['You send', '10 KNF Coin'])
    expect(receiveSide()).toBe('≈1.2345678 LTC Testnet')
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })


  it('turns up again — re-mined, or under the new id of a fee bump — and the order moves forward again', async () => {
    await renderAt(f.NOW, [confirming(), sentBack(), confirming({ tx_deposit_id: BUMPED_TX, confirm_count: 0 })])
    await poll()
    expect(status()).toBe('Awaiting deposit')

    await poll()

    expect(status()).toBe('Confirming')
    expect(confirmations()).toBe('0 of 2')
    expect(headline()).toBe('Confirming your deposit')
    expect(countdown()).toBeNull()
  })
})







// -----------------------------------------------------------
// A deposit that vanished after the deadline
// -----------------------------------------------------------
//
// The deadline stops mattering once a deposit is seen — until
// it vanishes, and the order is back to awaiting one. The
// worker still watches an expired order's address for a day,
// so a deposit mined after all takes the order back up.
// -----------------------------------------------------------

describe('Order page — a deposit that vanished after the deadline', () => {

  it('the countdown comes back at 00:00, and the next answer expires the order', async () => {
    await renderAt(AFTER_DEADLINE, [confirming(), sentBack(), expiredAfterRevert()])
    expect(countdown()).toBeNull()
    expect(within(main()).getByText(NO_TIME_LIMIT)).toBeInTheDocument()

    await poll()

    expect(status()).toBe('Awaiting deposit')
    expect(countdown()).toHaveTextContent(/^00:00$/)
    expect(countdown()).toHaveClass('text-amber-300')

    await poll()

    expect(status()).toBe('Expired')
    expect(headline()).toBe('Order expired')
    expect(countdown()).toBeNull()
    expect(marks()).toEqual(['!', '2', '3', '4', '5'])
  })


  it.each([
    ['as the backend reports it', {}],
    ['with the stale amount an older backend left on it', STALE],
  ])('expired, it does not say the coins were sent — %s', async (_, changes) => {
    await renderAt(AFTER_DEADLINE, [expiredAfterRevert(changes)])

    expect(headline()).toBe('Order expired')
    expect(sendSide()).toEqual(['You send', '10 KNF Coin'])
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })


  it('mined after all, the deposit takes the expired order back up', async () => {
    await renderAt(AFTER_DEADLINE, [expiredAfterRevert(), confirming({ confirm_count: 0 })])
    expect(status()).toBe('Expired')

    await poll()

    expect(status()).toBe('Confirming')
    expect(headline()).toBe('Confirming your deposit')
    expect(within(main()).getByText(NO_TIME_LIMIT)).toBeInTheDocument()
    expect(sendSide()).toEqual(['You sent', '10 KNF Coin'])
    expect(countdown()).toBeNull()
  })
})







// -----------------------------------------------------------
// A deposit that vanished while the payout waited
// -----------------------------------------------------------
//
// The worker checks the deposit once more before it builds the
// payout: gone, the order is back to awaiting it; back in the
// mempool, back to confirming. Either way the locked rate and
// the payout computed from it are undone.
// -----------------------------------------------------------

describe('Order page — a deposit that vanished while the payout waited', () => {

  it('gone: the order is back to awaiting its deposit, the payout an estimate at the quote again', async () => {
    await renderAt(f.NOW, [sending(), sentBack()])
    expect(receiveSide()).toBe('1.25 LTC Testnet')

    await poll()

    expect(status()).toBe('Awaiting deposit')
    expect(sendSide()).toEqual(['You send', '10 KNF Coin'])
    expect(receiveSide()).toBe('≈1.2345678 LTC Testnet')
    expect(within(main()).getByText(wholeText('Send 10 KNF Coin to this address:'))).toBeInTheDocument()
  })


  it('back in the mempool: the order is confirming again, the payout estimated until the rate locks anew', async () => {
    await renderAt(f.NOW, [sending(), confirming({ confirm_count: 0 })])

    await poll()

    expect(status()).toBe('Confirming')
    expect(confirmations()).toBe('0 of 2')
    expect(sendSide()).toEqual(['You sent', '10 KNF Coin'])
    expect(receiveSide()).toBe('≈1.2345678 LTC Testnet')
  })
})







// -----------------------------------------------------------
// A deposit taken back after the payout
// -----------------------------------------------------------
//
// A payout cannot be called back: the worker keeps watching a
// completed order's deposit, and one the chain took back
// reverses the order — until the chain holds it again.
// -----------------------------------------------------------

describe('Order page — a deposit taken back after the payout', () => {

  it('the completed order turns reversed: the deposit struck through, the payout kept', async () => {
    await renderAt(f.NOW, [completed(), reversed()])
    expect(headline()).toBe('Swap complete')

    await poll()

    expect(status()).toBe('Reversed')
    expect(headline()).toBe('Deposit reversed')
    expect(marks()).toEqual(['✓', '✓', '✓', '✓', '✕'])
    expect(within(card('Swap')).getByText('Deposit reversed').nextElementSibling.textContent).toBe('10 KNF Coin')
    expect(within(card('Swap')).getByText('You received').nextElementSibling.textContent).toBe('1.25 LTC Testnet')
  })


  it('once the chain holds the deposit again, the order is complete again', async () => {
    await renderAt(f.NOW, [reversed(), completed()])

    await poll()

    expect(status()).toBe('Completed')
    expect(headline()).toBe('Swap complete')
    expect(marks()).toEqual(['✓', '✓', '✓', '✓', '✓'])
  })
})







// -----------------------------------------------------------
// A top-up that vanished before it confirmed
// -----------------------------------------------------------
//
// The amounts follow a second payment that left the chain
// before it confirmed.
// -----------------------------------------------------------

describe('Order page — a top-up that vanished before it confirmed', () => {

  it('takes the amounts back down, and the note about a different deposit goes', async () => {
    await renderAt(f.NOW, [confirming({ received_amount: 12.5 }), confirming()])
    expect(sendSide()).toEqual(['You sent', '12.5 KNF Coin'])
    expect(receiveSide()).toBe('≈1.54320975 LTC Testnet')
    expect(within(main()).getByText(MISMATCH)).toBeInTheDocument()

    await poll()

    expect(sendSide()).toEqual(['You sent', '10 KNF Coin'])
    expect(receiveSide()).toBe('≈1.2345678 LTC Testnet')
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })
})
