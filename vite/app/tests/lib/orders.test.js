// -----------------------------------------------------------
//  [*] Tests — ORDER_STATUS, the statuses an order goes
//      through, and the rules the pages read an order by
//
//  The pages compare an order's status with these constants,
//  so they must carry the backend's own strings — the ten
//  the order worker writes: five while the order moves, five
//  that end it. hasReceivedCoins is the rule both pages read
//  an order's received amount by: coins sent, unless the
//  order waits for its deposit or expired; sendsCoinsBack
//  tells an order whose coins go back instead of being
//  exchanged; takesCoins whether its address still takes
//  coins to exchange — only until the rate is locked;
//  payoutConfirming and shownStatus show an order whose
//  payout is out as completed while the payout confirms.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { ORDER_STATUS, hasReceivedCoins, payoutConfirming, sendsCoinsBack, shownStatus, takesCoins } from '@/pages/Exchange/lib/orders.js'


// Every status the backend writes
const STATUSES = Object.values(ORDER_STATUS)







// -----------------------------------------------------------
// ORDER_STATUS
// -----------------------------------------------------------
//
// The constants the pages compare an order's status with
// carry the backend's own strings.
// -----------------------------------------------------------

describe('ORDER_STATUS', () => {

  it('names the ten statuses the backend\'s worker writes, by its own strings', () => {
    expect(ORDER_STATUS).toEqual({
      AWAITING_DEPOSIT: 'awaiting_deposit',
      AWAITING_CONFIRMATIONS: 'awaiting_confirmations',
      EXCHANGING: 'exchanging',
      SENDING: 'sending',
      REFUNDING: 'refunding',
      COMPLETED: 'completed',
      EXPIRED: 'expired',
      REFUNDED: 'refunded',
      FAILED: 'failed',
      REVERSED: 'reversed',
    })
  })
})







// -----------------------------------------------------------
// hasReceivedCoins
// -----------------------------------------------------------
//
// When an order's received amount counts as coins sent: on
// every status but awaiting the deposit and expired, and
// never when nothing arrived.
// -----------------------------------------------------------

describe('hasReceivedCoins', () => {

  it.each(['awaiting_confirmations', 'exchanging', 'sending', 'refunding', 'completed', 'refunded', 'failed', 'reversed'])('an order %s with coins received has them', (status) => {
    expect(hasReceivedCoins({ status, receivedAmount: 0.5 })).toBe(true)
  })


  it.each([0, null, undefined])('an order whose received amount is %s has none', (receivedAmount) => {
    expect(hasReceivedCoins({ status: 'awaiting_confirmations', receivedAmount })).toBe(false)
  })


  it.each(['awaiting_deposit', 'expired'])('an order %s has none, whatever amount it still carries', (status) => {
    expect(hasReceivedCoins({ status, receivedAmount: 10 })).toBe(false)
  })
})







// -----------------------------------------------------------
// sendsCoinsBack
// -----------------------------------------------------------
//
// An order whose coins go back instead of being exchanged:
// refunding, or refunded — no other.
// -----------------------------------------------------------

describe('sendsCoinsBack', () => {

  it.each(['refunding', 'refunded'])('an order %s sends its coins back', (status) => {
    expect(sendsCoinsBack({ status })).toBe(true)
  })


  it('an order of any other status does not', () => {
    for (const status of STATUSES.filter((status) => !['refunding', 'refunded'].includes(status))) {
      expect(sendsCoinsBack({ status }), status).toBe(false)
    }
  })
})







// -----------------------------------------------------------
// takesCoins
// -----------------------------------------------------------
//
// Whether coins sent to an order's address now would still
// be exchanged: until its rate is locked, never after.
// -----------------------------------------------------------

describe('takesCoins', () => {

  it.each(['awaiting_deposit', 'awaiting_confirmations', 'exchanging'])('an order %s still takes coins', (status) => {
    expect(takesCoins({ status })).toBe(true)
  })


  it.each(['sending', 'refunding', 'completed', 'expired', 'refunded', 'failed', 'reversed'])('an order %s takes no more', (status) => {
    expect(takesCoins({ status })).toBe(false)
  })


  it('nor does one whose status the frontend does not know', () => {
    expect(takesCoins({ status: 'cancelled' })).toBe(false)
  })
})







// -----------------------------------------------------------
// payoutConfirming and shownStatus
// -----------------------------------------------------------
//
// An order whose payout is out — sending, its payout's id
// known, no failure on record — is shown as completed while
// the payout confirms; every other order with its own status.
// -----------------------------------------------------------

describe('payoutConfirming and shownStatus', () => {

  it('a payout out with no failure on record is confirming — the order shown as completed', () => {
    const order = { status: 'sending', txSendId: 'ab'.repeat(32), error: null }
    expect(payoutConfirming(order)).toBe(true)
    expect(shownStatus(order)).toBe('completed')
  })


  it.each([
    ['not built yet', { txSendId: null, error: null }],
    ['held up before it was built', { txSendId: null, error: 'Electrum 127.0.0.1:1 unreachable: timed out' }],
    ['whose broadcast failed', { txSendId: 'ab'.repeat(32), error: 'Electrum 127.0.0.1:1 unreachable: timed out' }],
  ])('a payout %s is not — the order still sending', (_, payout) => {
    const order = { status: 'sending', ...payout }
    expect(payoutConfirming(order)).toBe(false)
    expect(shownStatus(order)).toBe('sending')
  })


  it.each(STATUSES.filter((status) => status !== 'sending'))('an order %s is shown with its own status', (status) => {
    const order = { status, txSendId: 'ab'.repeat(32), error: null }
    expect(payoutConfirming(order)).toBe(false)
    expect(shownStatus(order)).toBe(status)
  })
})
