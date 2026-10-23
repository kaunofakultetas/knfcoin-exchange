// -----------------------------------------------------------
//  [*] Tests — Order page: what it tells about the swap
//
//  The cards under the status: the payment while the deposit
//  is awaited, the swap (what is sent, what is received or
//  sent back, each side marked with its coin's logo — or its
//  dot when the order carries none — and the rate), the coins
//  sent back, and the details (the addresses and the
//  transactions); and the notices that explain an order's
//  surprises:
//    - while the deposit is awaited: the agreed amount to
//      send, to which address (copied exactly, encoded in the
//      QR code captioned with the amount), the estimate at the
//      quoted rate, the note that the rate locks on
//      confirmation, and the address the payout goes to
//    - once coins arrived: the past tense and the amount
//      actually received, the payout estimated from it — exact
//      at the locked rate once locked, received once done — no
//      more payment card, the deposit address among the
//      details, and a note when the deposit differs from the
//      agreed amount (a difference under a satoshi is none)
//    - when something went wrong: a payout delayed — retried,
//      the backend's words beneath — a failed order with its
//      reason and its payout struck through, without a promise
//      of an exchange, what an expired order never received,
//      and a reversed order's deposit struck through beside
//      the payout it was paid
//    - when the coins go back: what is sent back instead of a
//      payout (exactly what the refunds pay, about what
//      arrived before there are any), why the order was not
//      exchanged, each refund with the address it pays and
//      whether it has confirmed — and on an order that went
//      through, the coins it sent back that came after the
//      rate lock
//    - the deposit address after the rate lock takes no more
//      coins: no QR code, and a warning that whatever is sent
//      now goes back — none on a reversed order; an expired
//      order offers no QR code either
//    - the transactions, once there are any — on a reversed
//      order, each marked with whether the main chain holds it
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { card, orderAnswer, qrCode, qrCodes, qrFor, renderOrder } from '../../support/order/page'
import { wholeText } from '../../support/regions'
import * as f from '../../support/backend/fixtures'


const main = () => screen.getByRole('main')

// The page with its order in
const renderLoaded = async (id) => {
  const view = renderOrder(id)
  await within(main()).findByRole('heading', { level: 1, name: `Order #${id}` })
  return view
}

// The send and receive halves of the swap: a label and the
// amount under it
const side = (label) => within(main()).getByText(label).nextElementSibling.textContent

// The coin logo beside one half of the swap, by the URL it
// was drawn from — nothing while the coin wears its dot
const logoBeside = (label) => {
  const mark = within(main()).getByText(label).parentElement.previousElementSibling
  return mark.tagName === 'IMG' ? mark.getAttribute('src') : null
}

// The rate line: what one coin fetches, and whether that is
// quoted or locked
const rate = () => within(card('Swap')).getByText('Rate').nextElementSibling

// The sentence explaining a deposit that differs from the
// agreed amount
const MISMATCH = /instead of the agreed .* — the payout follows what actually arrived\.$/

// The warning under an address that takes no more coins
const NO_MORE_COINS = 'Do not send more to this address — this order takes no more coins. Anything that arrives within a day goes back to the address it came from.'







// -----------------------------------------------------------
// While the deposit is awaited
// -----------------------------------------------------------
//
// What to send, where and for what: the agreed amount, the
// deposit address to copy or scan, the quoted rate and the
// destination.
// -----------------------------------------------------------

describe('Order summary — while the deposit is awaited', () => {

  it('shows both sides of the swap: the agreed amount sent, and the estimate received', async () => {
    await renderLoaded(f.AWAITING_ID)
    expect(side('You send')).toBe('10 KNF Coin')
    expect(side('You receive')).toBe('≈1.2345678 LTC Testnet')
  })


  it.each([
    ['KNF Coin → LTC Testnet', f.AWAITING_ID, 'You send', [f.ICONS[f.KNF], f.ICONS[f.LTC]]],
    ['LTC Testnet → KNF Coin', f.CONFIRMING_ID, 'You sent', [f.ICONS[f.LTC], f.ICONS[f.KNF]]],
  ])('marks each side with its coin\'s logo — %s', async (_, id, sendLabel, logos) => {
    await renderLoaded(id)
    expect([logoBeside(sendLabel), logoBeside('You receive')]).toEqual(logos)
  })


  it('a coin its order has no logo for wears its dot', async () => {
    orderAnswer(f.AWAITING_ID, { to_icon: null })
    await renderLoaded(f.AWAITING_ID)
    expect([logoBeside('You send'), logoBeside('You receive')]).toEqual([f.ICONS[f.KNF], null])
  })


  it('quotes the rate of the order — quoted, until the deposit confirms', async () => {
    await renderLoaded(f.AWAITING_ID)
    expect(rate()).toHaveTextContent(/^1 KNF Coin ≈ 0\.12345678 LTC Testnet$/)
    expect(rate().nextElementSibling).toHaveTextContent(/^Quoted$/)
  })


  it('says what to send and where, and that the rate locks once the deposit confirms', async () => {
    await renderLoaded(f.AWAITING_ID)
    const deposit = f.orderById(f.AWAITING_ID).deposit_address
    const payment = card('Payment')

    expect(within(payment).getByText(wholeText('Send 10 KNF Coin to this address:'))).toBeInTheDocument()
    expect(within(payment).getByText(deposit)).toBeInTheDocument()
    expect(within(payment).getByText('The final rate is locked in once your deposit confirms.')).toBeInTheDocument()
  })


  it('names where the payout goes: the student\'s own address of the asset received', async () => {
    await renderLoaded(f.AWAITING_ID)
    const details = card('Order details')
    expect(within(details).getByText('Your LTC Testnet address')).toBeInTheDocument()
    expect(within(details).getByText(f.STUDENT_LTC)).toBeInTheDocument()
  })


  it('copying the deposit address puts exactly it on the clipboard', async () => {
    const { user } = await renderLoaded(f.AWAITING_ID)
    const deposit = f.orderById(f.AWAITING_ID).deposit_address
    const write = vi.spyOn(navigator.clipboard, 'writeText')

    await user.click(within(within(main()).getByText(deposit).parentElement).getByRole('button', { name: 'Copy' }))

    expect(write).toHaveBeenCalledExactlyOnceWith(deposit)
  })


  it('encodes the deposit address in the QR code, captioned with the amount to pay', async () => {
    await renderLoaded(f.AWAITING_ID)
    const { deposit_address: deposit, destination } = f.orderById(f.AWAITING_ID)

    expect(qrCode().innerHTML).toBe(qrFor(deposit).innerHTML)
    expect(qrCode().innerHTML).not.toBe(qrFor(destination).innerHTML)
    expect(within(card('Payment')).getByText('Scan to pay 10 KNF Coin')).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// Once the deposit arrived
// -----------------------------------------------------------
//
// The swap in the past tense: the amount actually received,
// the payout estimated from it until the rate is locked and
// exact after, a note when it differs from the agreed amount;
// no more payment to make.
// -----------------------------------------------------------

describe('Order summary — once the deposit arrived', () => {

  it('speaks of what was sent in the past tense, with the amount received', async () => {
    await renderLoaded(f.CONFIRMING_ID)
    expect(within(main()).queryByText('You send')).toBeNull()
    expect(side('You sent')).toBe('0.5 LTC Testnet')
  })


  it('estimates the payout from the deposit until the rate is locked', async () => {
    orderAnswer(f.CONFIRMING_ID, { received_amount: 0.6 })
    await renderLoaded(f.CONFIRMING_ID)
    expect(side('You sent')).toBe('0.6 LTC Testnet')
    expect(side('You receive')).toBe('≈4.8600004 KNF Coin')
  })


  it('shows the exact payout, and the locked rate, once the backend locked it', async () => {
    orderAnswer(f.SENDING_ID, { locked_rate: 0.1, to_amount: 1.25 })
    await renderLoaded(f.SENDING_ID)
    expect(side('You receive')).toBe('1.25 LTC Testnet')
    expect(rate()).toHaveTextContent(/^1 KNF Coin ≈ 0\.1 LTC Testnet$/)
    expect(rate().nextElementSibling).toHaveTextContent(/^Locked$/)
  })


  it('a completed order says what was received', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(side('You sent')).toBe('100 KNF Coin')
    expect(side('You received')).toBe('12.345678 LTC Testnet')
  })


  it('a payout out reads as received while it confirms', async () => {
    orderAnswer(f.SENDING_ID, { error: null, tx_send_id: f.PAYOUT_TXID })
    await renderLoaded(f.SENDING_ID)
    expect(side('You received')).toBe('1.54320975 LTC Testnet')
  })


  it('no longer asks for a payment: no payment card, no QR code — the address among the details', async () => {
    await renderLoaded(f.CONFIRMING_ID)
    expect(screen.queryByRole('region', { name: 'Payment' })).toBeNull()
    expect(qrCodes()).toHaveLength(0)
    expect(within(main()).queryByText(/^Send /)).toBeNull()
    expect(within(card('Order details')).getByText('Deposit address')).toBeInTheDocument()
    expect(within(card('Order details')).getByText(f.orderById(f.CONFIRMING_ID).deposit_address)).toBeInTheDocument()
  })


  it('explains a deposit that differs from the agreed amount', async () => {
    await renderLoaded(f.SENDING_ID)
    expect(within(card('Swap')).getByText('You sent 12.5 KNF Coin instead of the agreed 10 — the payout follows what actually arrived.')).toBeInTheDocument()
  })


  it('a deposit of exactly the agreed amount needs no explanation', async () => {
    await renderLoaded(f.EXCHANGING_ID)
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })


  it('a difference smaller than a satoshi is no difference', async () => {
    orderAnswer(f.EXCHANGING_ID, { received_amount: 25.000000001 })
    await renderLoaded(f.EXCHANGING_ID)
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })
})







// -----------------------------------------------------------
// When something went wrong
// -----------------------------------------------------------
//
// The notices an order's trouble brings: a payout delayed, an
// order failed — without a promise of an exchange — and the
// deposit an expired order never received.
// -----------------------------------------------------------

describe('Order summary — when something went wrong', () => {

  it('a payout not sent yet is delayed and retried — the backend\'s words kept beneath', async () => {
    await renderLoaded(f.SENDING_ID)
    const status = card('Order status')
    expect(within(status).getByText('Payout delayed')).toBeInTheDocument()
    expect(within(status).getByText('It could not be sent yet — the exchange keeps trying automatically, there is nothing to do on your side.')).toBeInTheDocument()
    expect(within(status).getByText(f.PAYOUT_PENDING)).toBeInTheDocument()
  })


  it('a failed order says so, with the worker\'s reason — and strikes through the payout', async () => {
    await renderLoaded(f.FAILED_ID)
    const status = card('Order status')
    expect(within(status).getByText('This order could not be exchanged, and its coins could not be sent back either.')).toBeInTheDocument()
    expect(within(status).getByText(f.DUST_FAILURE)).toBeInTheDocument()
    expect(side('You sent')).toBe('0.00001 KNF Coin')
    expect(side('Not paid out')).toBe('0.00000123 LTC Testnet')
    expect(within(main()).queryByText('You receive')).toBeNull()
  })


  it('a failed order does not claim its deposit is being exchanged, nor quote a rate', async () => {
    await renderLoaded(f.FAILED_ID)
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
    expect(within(card('Swap')).queryByText('Rate')).toBeNull()
  })


  it('an expired order shows the amount it waited for and the address it never received it on', async () => {
    await renderLoaded(f.EXPIRED_ID)
    expect(side('You send')).toBe('1 LTC Testnet')
    expect(side('You receive')).toBe('≈8.10000066 KNF Coin')
    expect(within(card('Order details')).getByText(f.orderById(f.EXPIRED_ID).deposit_address)).toBeInTheDocument()
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
  })


  it('a reversed order strikes through the deposit the chain took back, beside the payout it was paid', async () => {
    await renderLoaded(f.REVERSED_ID)
    // The status card's headline reads the same words
    expect(within(card('Swap')).getByText('Deposit reversed').nextElementSibling.textContent).toBe('50 KNF Coin')
    expect(side('You received')).toBe('6.172839 LTC Testnet')
    expect(within(main()).queryByText('You sent')).toBeNull()
  })


  it('an order with nothing wrong shows no notice', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(within(main()).queryByText('Payout delayed')).toBeNull()
    expect(within(main()).queryByText('Reason:')).toBeNull()
  })
})







// -----------------------------------------------------------
// When the coins go back
// -----------------------------------------------------------
//
// An order that could not go through: what goes back instead
// of a payout, why, and each refund with where it went — and
// the coins an order that went through sent back.
// -----------------------------------------------------------

describe('Order summary — when the coins go back', () => {

  it('says what is sent back instead of what it would have paid — exactly what the refunds pay', async () => {
    await renderLoaded(f.REFUNDING_ID)
    expect(side('You sent')).toBe('1,500 KNF Coin')
    expect(side('Sent back to you')).toBe('1,499.999989 KNF Coin')
    expect(within(main()).queryByText('You receive')).toBeNull()
    expect(logoBeside('Sent back to you')).toBe(f.ICONS[f.KNF])
  })


  it('before its refund is signed, about what arrived', async () => {
    orderAnswer(f.REFUNDING_ID, { refunds: [] })
    await renderLoaded(f.REFUNDING_ID)
    expect(side('Sent back to you')).toBe('≈1,500 KNF Coin')
  })


  it('says why the order was not exchanged', async () => {
    await renderLoaded(f.REFUNDING_ID)
    expect(within(card('Order status')).getByText(f.REFUND_SHORTFALL)).toBeInTheDocument()
    expect(within(main()).queryByText('Payout delayed')).toBeNull()
  })


  it.each([
    ['on their way back', f.REFUNDING_ID, 'This order could not be exchanged, so your KNF Coin are on their way back to the address they came from.'],
    ['already back', f.REFUNDED_ID, 'This order could not be exchanged, so your KNF Coin went back to the address they came from.'],
  ])('with its coins %s, the status card says so', async (_, id, text) => {
    await renderLoaded(id)
    expect(within(card('Order status')).getByText(text)).toBeInTheDocument()
  })


  it('makes no promise of an exchange: no note on the amount, no rate, no payout address', async () => {
    await renderLoaded(f.REFUNDING_ID)
    expect(within(main()).queryByText(MISMATCH)).toBeNull()
    expect(within(card('Swap')).queryByText('Rate')).toBeNull()
    expect(within(main()).queryByText('Your LTC Testnet address')).toBeNull()
  })


  it.each([
    ['still confirming', f.REFUNDING_ID, '1,499.999989 KNF Coin', 'Confirming…', f.REFUND_PENDING_TXID],
    ['confirmed', f.REFUNDED_ID, '0.000019 KNF Coin', 'Confirmed', f.REFUND_CONFIRMED_TXID],
  ])('lists its refund — %s — with the address it pays', async (_, id, amount, state, txid) => {
    await renderLoaded(id)
    const refunds = card('Coins sent back')
    expect(within(refunds).getByText('Your KNF Coin sent back')).toBeInTheDocument()
    expect(within(refunds).getByText(amount)).toBeInTheDocument()
    expect(within(refunds).getByText(state)).toBeInTheDocument()
    expect(within(refunds).getByText(wholeText(`to ${f.STUDENT_KNF}`))).toBeInTheDocument()
    expect(within(refunds).getByText(`Refund tx: ${txid}`)).toBeInTheDocument()
  })


  it('a script the backend cannot name reads as the address it came from', async () => {
    const [refund] = f.orderById(f.REFUNDED_ID).refunds
    orderAnswer(f.REFUNDED_ID, { refunds: [{ ...refund, recipients: [{ address: null, amount: 0.000019 }] }] })
    await renderLoaded(f.REFUNDED_ID)
    expect(within(card('Coins sent back')).getByText(wholeText('to the address it came from'))).toBeInTheDocument()
  })


  it('an order that went through lists the coins it sent back that came after the rate lock', async () => {
    orderAnswer(f.COMPLETED_ID, {
      refunds: [{ txid: f.REFUND_PENDING_TXID, confirmed: true, created_at: 1791047000000, recipients: [{ address: f.STUDENT_KNF, amount: 4.999989 }] }],
    })
    await renderLoaded(f.COMPLETED_ID)
    const refunds = card('Coins sent back')
    expect(within(refunds).getByText('Sent back — these arrived after the rate was locked')).toBeInTheDocument()
    expect(within(refunds).getByText('4.999989 KNF Coin')).toBeInTheDocument()
    expect(within(refunds).getByText('Confirmed')).toBeInTheDocument()
    expect(side('You received')).toBe('12.345678 LTC Testnet')
  })


  it('a failed order whose coins went back after all lists them as its own', async () => {
    // Too small to pay out; the payment that followed went back with it
    orderAnswer(f.FAILED_ID, {
      refunds: [{ txid: f.REFUND_CONFIRMED_TXID, confirmed: true, created_at: 1791028000000, recipients: [{ address: f.STUDENT_KNF, amount: 9.99999 }] }],
    })
    await renderLoaded(f.FAILED_ID)
    expect(within(card('Coins sent back')).getByText('Your KNF Coin sent back')).toBeInTheDocument()
  })


  it('an order without refunds has no such card', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(screen.queryByRole('region', { name: 'Coins sent back' })).toBeNull()
  })
})







// -----------------------------------------------------------
// The address after the rate lock
// -----------------------------------------------------------
//
// The deposit address is offered to pay only while the
// deposit is awaited; once the rate is locked it takes no
// more coins, and the page warns that what is sent now goes
// back.
// -----------------------------------------------------------

describe('Order summary — the address after the rate lock', () => {

  it('while the deposit is awaited, the address is offered to pay — with its QR code', async () => {
    await renderLoaded(f.AWAITING_ID)
    expect(qrCodes()).toHaveLength(1)
    expect(within(main()).queryByText(NO_MORE_COINS)).toBeNull()
  })


  it.each([
    ['confirming', f.CONFIRMING_ID],
    ['exchanging', f.EXCHANGING_ID],
  ])('while %s, coins still count — no QR code to pay more, and no warning', async (_, id) => {
    await renderLoaded(id)
    expect(qrCodes()).toHaveLength(0)
    expect(within(main()).queryByText(NO_MORE_COINS)).toBeNull()
  })


  it.each([
    ['sending', f.SENDING_ID],
    ['completed', f.COMPLETED_ID],
    ['refunding', f.REFUNDING_ID],
    ['refunded', f.REFUNDED_ID],
    ['failed', f.FAILED_ID],
  ])('%s, it takes no more: no QR code, and a warning that what comes now goes back', async (_, id) => {
    await renderLoaded(id)
    expect(qrCodes()).toHaveLength(0)
    expect(within(card('Order details')).getByText(NO_MORE_COINS)).toBeInTheDocument()
    expect(within(card('Order details')).getByText(f.orderById(id).deposit_address)).toBeInTheDocument()
  })


  it('a reversed order offers no QR code either — and no warning', async () => {
    await renderLoaded(f.REVERSED_ID)
    expect(qrCodes()).toHaveLength(0)
    expect(within(main()).queryByText(/^Do not send more to this address/)).toBeNull()
  })


  it('an expired order offers no QR code either — and no warning', async () => {
    await renderLoaded(f.EXPIRED_ID)
    expect(qrCodes()).toHaveLength(0)
    expect(within(main()).queryByText(NO_MORE_COINS)).toBeNull()
  })
})







// -----------------------------------------------------------
// The transactions
// -----------------------------------------------------------
//
// The deposit and the payout transactions among the details,
// each once there is one — and on a reversed order, whether
// the main chain still holds each.
// -----------------------------------------------------------

describe('Order details — the transactions', () => {

  it('shows the deposit transaction once there is one', async () => {
    await renderLoaded(f.CONFIRMING_ID)
    const details = card('Order details')
    expect(within(details).getByText('Deposit transaction')).toBeInTheDocument()
    expect(within(details).getByText(f.orderById(f.CONFIRMING_ID).tx_deposit_id)).toBeInTheDocument()
  })


  it('shows the payout transaction once there is one', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(within(card('Order details')).getByText(f.PAYOUT_TXID)).toBeInTheDocument()
  })


  it('shows no payout transaction before the payout', async () => {
    await renderLoaded(f.SENDING_ID)
    expect(within(card('Order details')).queryByText('Payout transaction')).toBeNull()
  })


  it('on a reversed order, marks the deposit as no longer in the main chain, and the payout as in it', async () => {
    await renderLoaded(f.REVERSED_ID)
    const row = (label) => within(card('Order details')).getByText(label).nextElementSibling
    expect(within(row('Deposit transaction')).getByText(f.orderById(f.REVERSED_ID).tx_deposit_id)).toBeInTheDocument()
    expect(within(row('Deposit transaction')).getByText('No longer in the main chain')).toBeInTheDocument()
    expect(within(row('Payout transaction')).getByText('In the main chain')).toBeInTheDocument()
  })


  it('marks no transaction on an order that is not reversed', async () => {
    await renderLoaded(f.COMPLETED_ID)
    expect(within(card('Order details')).queryByText(/main chain/)).toBeNull()
  })


  it('shows no deposit transaction — nor the deposit address, on the payment card — before the deposit', async () => {
    await renderLoaded(f.AWAITING_ID)
    expect(within(card('Order details')).queryByText('Deposit transaction')).toBeNull()
    expect(within(card('Order details')).queryByText('Deposit address')).toBeNull()
  })
})
