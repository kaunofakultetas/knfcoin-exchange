// -----------------------------------------------------------
//  [*] Tests — Order page: the status card and its steps
//
//  The status card, right under the swap, tells the order's
//  status in plain words — a headline per status, and what
//  happens now or became of it — over the five steps of the
//  pipeline: Deposit, Confirming, Exchanging, Sending, Done.
//  They are a list whose current step is marked as such: a
//  tick on each step passed, a spinner on the current one
//  (with the confirmations seen of those required while
//  confirming), the number of each step ahead; an expired
//  order stopped at its deposit ("!"), a failed one at its
//  payout ("✕"), a reversed one — its deposit taken back by
//  the chain after the payout — short of done ("✕"). An order
//  whose coins go back follows the refund's steps after the
//  rate lock — Sending back, Sent back. An order whose payout
//  is out reads as done, its payout noted as confirming.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import { REFUND_STEP_LABELS, STEP_LABELS, card, orderAnswer, progressSteps, renderOrder } from '../../support/order/page'
import * as f from '../../support/backend/fixtures'


const main = () => screen.getByRole('main')

// The page with its order in
const renderLoaded = async (id) => {
  const view = renderOrder(id)
  await within(main()).findByRole('heading', { level: 1, name: `Order #${id}` })
  return view
}

const marks = () => progressSteps().map((step) => step.mark)
const current = () => progressSteps().filter((step) => step.current).map((step) => step.label)

// The status card's headline
const headline = () => within(card('Order status')).getByRole('heading', { level: 2 }).textContent







// -----------------------------------------------------------
// The steps
// -----------------------------------------------------------
//
// The five steps of the pipeline — or of the refund — and how
// each status marks them.
// -----------------------------------------------------------

describe('Order progress — the steps', () => {

  it('names the five steps of the pipeline, in order', async () => {
    await renderLoaded(f.AWAITING_ID)
    expect(progressSteps().map((step) => step.label)).toEqual(STEP_LABELS)
  })


  it.each([
    ['awaiting_deposit', f.AWAITING_ID, ['', '2', '3', '4', '5'], ['Deposit']],
    ['awaiting_confirmations', f.CONFIRMING_ID, ['✓', '', '3', '4', '5'], ['Confirming']],
    ['exchanging', f.EXCHANGING_ID, ['✓', '✓', '', '4', '5'], ['Exchanging']],
    ['sending', f.SENDING_ID, ['✓', '✓', '✓', '', '5'], ['Sending']],
    ['completed', f.COMPLETED_ID, ['✓', '✓', '✓', '✓', '✓'], []],
    ['expired', f.EXPIRED_ID, ['!', '2', '3', '4', '5'], []],
    ['failed', f.FAILED_ID, ['✓', '✓', '✓', '✕', '5'], []],
    ['reversed', f.REVERSED_ID, ['✓', '✓', '✓', '✓', '✕'], []],
  ])('%s: the steps read %j, the current one %j', async (_, id, expected, currentStep) => {
    await renderLoaded(id)
    expect(marks()).toEqual(expected)
    expect(current()).toEqual(currentStep)
  })


  it('a status it does not know marks no step', async () => {
    orderAnswer(f.COMPLETED_ID, { status: 'cancelled' })
    await renderLoaded(f.COMPLETED_ID)
    expect(marks()).toEqual(['1', '2', '3', '4', '5'])
    expect(current()).toEqual([])
  })


  it('an order whose coins go back follows the refund\'s steps after the rate lock', async () => {
    await renderLoaded(f.REFUNDING_ID)
    expect(progressSteps().map((step) => step.label)).toEqual(REFUND_STEP_LABELS)
    expect(within(main()).queryByText('Done')).toBeNull()
  })


  it.each([
    ['refunding', f.REFUNDING_ID, ['✓', '✓', '✓', '', '5'], ['Sending back']],
    ['refunded', f.REFUNDED_ID, ['✓', '✓', '✓', '✓', '✓'], []],
  ])('%s: the refund\'s steps read %j, the current one %j', async (_, id, expected, currentStep) => {
    await renderLoaded(id)
    expect(marks()).toEqual(expected)
    expect(current()).toEqual(currentStep)
  })
})







// -----------------------------------------------------------
// While confirming
// -----------------------------------------------------------
//
// The current step counts the confirmations seen of those
// required; no other step carries a note.
// -----------------------------------------------------------

describe('Order progress — while confirming', () => {

  it.each([
    [1, 2, '1 of 2'],
    [0, 2, '0 of 2'],
    [1, 6, '1 of 6'],
  ])('%i confirmations of %i read "%s" under the current step', async (count, target, note) => {
    orderAnswer(f.CONFIRMING_ID, { confirm_count: count, confirm_target: target })
    await renderLoaded(f.CONFIRMING_ID)
    expect(progressSteps().map((step) => step.note)).toEqual([null, note, null, null, null])
  })


  it('past the confirmations, no step carries a note', async () => {
    await renderLoaded(f.EXCHANGING_ID)
    expect(progressSteps().map((step) => step.note)).toEqual([null, null, null, null, null])
  })
})







// -----------------------------------------------------------
// The status in words
// -----------------------------------------------------------
//
// The status card's headline for every status, what it says
// happens now or became of the order, and the name the
// backend wrote for a status the page does not know.
// -----------------------------------------------------------

describe('Order status card', () => {

  it.each([
    ['awaiting_deposit', f.AWAITING_ID, 'Waiting for your deposit'],
    ['awaiting_confirmations', f.CONFIRMING_ID, 'Confirming your deposit'],
    ['exchanging', f.EXCHANGING_ID, 'Locking the rate'],
    ['sending', f.SENDING_ID, 'Sending your LTC Testnet'],
    ['completed', f.COMPLETED_ID, 'Swap complete'],
    ['refunding', f.REFUNDING_ID, 'Sending your coins back'],
    ['refunded', f.REFUNDED_ID, 'Coins sent back'],
    ['expired', f.EXPIRED_ID, 'Order expired'],
    ['failed', f.FAILED_ID, 'Order failed'],
    ['reversed', f.REVERSED_ID, 'Deposit reversed'],
  ])('%s reads "%s"', async (_, id, title) => {
    await renderLoaded(id)
    expect(headline()).toBe(title)
  })


  it('a reversed order says what was paid out, and that the chain took its deposit back', async () => {
    await renderLoaded(f.REVERSED_ID)
    expect(within(card('Order status')).getByText(
      '6.172839 LTC Testnet were paid out, but a reorganisation of the KNF Coin chain then took your deposit back out of it. The exchange paid for coins the chain no longer holds.',
    )).toBeInTheDocument()
  })


  it('a status it does not know is named as the backend wrote it', async () => {
    orderAnswer(f.COMPLETED_ID, { status: 'cancelled' })
    await renderLoaded(f.COMPLETED_ID)
    expect(headline()).toBe('Status: cancelled')
  })


  it('while confirming, says what arrived — and that time no longer runs', async () => {
    await renderLoaded(f.CONFIRMING_ID)
    expect(within(card('Order status')).getByText(
      '0.5 LTC Testnet arrived. No time limit any more — the swap completes automatically once the network has confirmed it.',
    )).toBeInTheDocument()
  })


  it('a payout not out yet goes out next', async () => {
    orderAnswer(f.SENDING_ID, { error: null, tx_send_id: null })
    await renderLoaded(f.SENDING_ID)
    expect(within(card('Order status')).getByText(
      'Your deposit is confirmed and the rate is locked — the payout goes out to your address next.',
    )).toBeInTheDocument()
  })


  it('a payout already out shows the order done — every step passed, the payout noted as confirming', async () => {
    orderAnswer(f.SENDING_ID, { error: null, tx_send_id: f.PAYOUT_TXID })
    await renderLoaded(f.SENDING_ID)
    expect(within(main()).getByRole('heading', { level: 1 }).parentElement.nextElementSibling.textContent).toBe('Completed')
    expect(headline()).toBe('Swap complete')
    expect(within(card('Order status')).getByText('1.54320975 LTC Testnet were paid out to your address.')).toBeInTheDocument()
    expect(within(card('Order status')).getByText('Payout confirming')).toBeInTheDocument()
    expect(marks()).toEqual(['✓', '✓', '✓', '✓', '✓'])
  })


  it('a payout whose last broadcast failed is still sending — no confirming note', async () => {
    orderAnswer(f.SENDING_ID, { tx_send_id: f.PAYOUT_TXID })
    await renderLoaded(f.SENDING_ID)
    expect(headline()).toBe('Sending your LTC Testnet')
    expect(within(main()).queryByText('Payout confirming')).toBeNull()
  })


  it('a completed order says what was paid out — its payout confirmed, no note', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(within(card('Order status')).getByText('12.345678 LTC Testnet were paid out to your address.')).toBeInTheDocument()
    expect(within(main()).queryByText('Payout confirming')).toBeNull()
  })
})
