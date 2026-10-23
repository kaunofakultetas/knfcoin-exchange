// -----------------------------------------------------------
//  [*] Tests — ExchangeApi, the client of /api/exchange
//
//  The one way the pages reach the backend: each call asks the
//  right endpoint (the order list's limit and an order's id
//  encoded into the URL), a new order goes out as JSON exactly
//  as the form built it, and what comes back is handed over in
//  the camelCase shape the pages read — every column a page
//  uses, renamed, and nothing else; an order's refunds always
//  a list, whatever came, and so are their recipients. A
//  failed request rejects
//  with the backend's own sentence when the answer carried
//  one, "Request failed" with the status when it did not, and
//  fetch's own error when nothing answered; an answer it cannot
//  read rejects too.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { given } from '../support/backend/server'
import { NETWORK_ERROR } from '../support/backend/contract'
import { TEST_ORIGIN } from '../support/location'
import * as f from '../support/backend/fixtures'
import { ExchangeApi } from '@/pages/Exchange/lib/api.js'


// The completed order as the pages receive it
const COMPLETED = {
  id: f.COMPLETED_ID,
  pair: 'KNF Coin -> LTC Testnet',
  fromAsset: 'KNF Coin',
  toAsset: 'LTC Testnet',
  fromAmount: 100,
  toAmount: 12.345678,
  rate: f.RATE_KNF_LTC,
  lockedRate: f.RATE_KNF_LTC,
  destination: f.STUDENT_LTC,
  status: 'completed',
  confirmTarget: 2,
  confirmCount: 2,
  depositAddress: 'knf1qxjg9pc8ddsxcxrag5ahg8a62wmx5mwudwzjv2z',
  depositScripthash: 'ed617934a077d16392a0d31fcfb441901375132341356f1a803087b7b4eb5c9b',
  receivedAmount: 100,
  txDepositId: 'e580d9e28b39c2724bb37bef433322eace1e14726d3cdb5d7d39b2038178c84c',
  txSendId: f.PAYOUT_TXID,
  error: null,
  fromIcon: '/api/exchange/icons/knf',
  toIcon: '/api/exchange/icons/ltc4',
  refunds: [],
  createdAt: 1791045600000,
  updatedAt: 1791046880000,
  expiresAt: 1791047400000,
}

// The refund of the order sending its coins back, as the
// pages receive it
const PENDING_REFUND = {
  txid: f.REFUND_PENDING_TXID,
  confirmed: false,
  createdAt: 1791105540000,
  recipients: [{ address: f.STUDENT_KNF, amount: 1499.999989 }],
}







// -----------------------------------------------------------
// The reads
// -----------------------------------------------------------
//
// The four GETs of ExchangeApi: what each asks the backend
// for, and the shape it hands the pages — orders and reserves
// camelized, the rates as they came.
// -----------------------------------------------------------

describe('ExchangeApi.getRates', () => {

  it('resolves the backend\'s snapshot as it is — the pairs, the limits, the logos and what can be paid out', async () => {
    expect(await ExchangeApi.getRates()).toEqual(f.rates)
  })
})


describe('ExchangeApi.getReserves', () => {

  it('hands over each reserve in the camelCase shape the page reads', async () => {
    const reserves = await ExchangeApi.getReserves()
    expect(reserves).toHaveLength(2)
    expect(reserves[0]).toEqual({
      network: 'knf',
      asset: 'KNF Coin',
      shortName: 'KNF',
      fullName: 'KNF Coin',
      blockExplorer: '/explorer',
      icon: '/api/exchange/icons/knf',
      address: f.RESERVE_KNF,
      confirmed: 4821.5,
      unconfirmed: 0,
      available: f.AVAILABLE[f.KNF],
      error: null,
    })
  })


  it('keeps a chain\'s error, and its missing balance, as they came', async () => {
    given.json('get', '/api/exchange/reserves', [{ ...f.reserves()[1], confirmed: null, unconfirmed: null, available: null, error: f.RESERVE_SYNCING }])
    expect(await ExchangeApi.getReserves()).toEqual([expect.objectContaining({ confirmed: null, unconfirmed: null, available: null, error: f.RESERVE_SYNCING })])
  })


  it('rejects an answer that is not a list', async () => {
    given.json('get', '/api/exchange/reserves', { knf: f.reserves()[0] })
    await expect(ExchangeApi.getReserves()).rejects.toThrow(TypeError)
  })
})


describe('ExchangeApi.listOrders', () => {

  it('asks for 20 orders unless told otherwise', async () => {
    const calls = given.capture('get', '/api/exchange/orders', [])
    await ExchangeApi.listOrders()
    expect(calls.map((call) => call.query)).toEqual([{ limit: '20' }])
  })


  it('asks for as many as the caller wants', async () => {
    const calls = given.capture('get', '/api/exchange/orders', [])
    await ExchangeApi.listOrders(5)
    expect(calls.map((call) => call.query)).toEqual([{ limit: '5' }])
  })


  it('hands over the rows in the backend\'s order, camelCased — the columns no page reads left behind', async () => {
    const orders = await ExchangeApi.listOrders(f.orders().length)
    expect(orders.map((order) => order.id)).toEqual(f.orders().map((row) => row.id))
    expect(orders.find((order) => order.id === f.COMPLETED_ID)).toEqual(COMPLETED)
  })
})


describe('ExchangeApi.getOrder', () => {

  it('asks for the order by its id and hands it over camelCased', async () => {
    expect(await ExchangeApi.getOrder(f.COMPLETED_ID)).toEqual(COMPLETED)
  })


  it('hands over an order\'s refunds camelCased, with who each one pays what', async () => {
    expect((await ExchangeApi.getOrder(f.REFUNDING_ID)).refunds).toEqual([PENDING_REFUND])
  })


  it.each([
    ['no refunds field at all', undefined, []],
    ['refunds that are not a list', 'refund-1', []],
    ['entries that are not objects', [null, 'refund-1', 42, { txid: 'aa', confirmed: true, created_at: 1, recipients: [] }],
      [{ txid: 'aa', confirmed: true, createdAt: 1, recipients: [] }]],
    ['recipients that are not a list, or not objects', [{ txid: 'aa', confirmed: 'yes', created_at: 1, recipients: [null, { address: null, amount: 2 }] },
      { txid: 'bb', confirmed: false, created_at: 2, recipients: 'everyone' }],
      [{ txid: 'aa', confirmed: false, createdAt: 1, recipients: [{ address: null, amount: 2 }] },
        { txid: 'bb', confirmed: false, createdAt: 2, recipients: [] }]],
  ])('an order with %s still hands over a list of refunds', async (_, refunds, camelized) => {
    given.json('get', `/api/exchange/orders/${f.COMPLETED_ID}`, { ...f.orderById(f.COMPLETED_ID), refunds })
    expect((await ExchangeApi.getOrder(f.COMPLETED_ID)).refunds).toEqual(camelized)
  })


  it('puts the id into the path encoded, whatever it holds', async () => {
    const calls = given.capture('get', '/api/exchange/orders/:orderId', f.orderById(f.COMPLETED_ID))
    await ExchangeApi.getOrder('A/B C?d')
    expect(calls.map((call) => call.url)).toEqual([`${TEST_ORIGIN}/api/exchange/orders/A%2FB%20C%3Fd`])
  })


  it('resolves nothing for a null body', async () => {
    given.json('get', `/api/exchange/orders/${f.COMPLETED_ID}`, null)
    expect(await ExchangeApi.getOrder(f.COMPLETED_ID)).toBeNull()
  })
})







// -----------------------------------------------------------
// The write
// -----------------------------------------------------------
//
// createOrder: the payload posted as JSON exactly as built,
// the created order handed over camelized.
// -----------------------------------------------------------

describe('ExchangeApi.createOrder', () => {

  it('POSTs the payload as JSON, exactly as the caller built it', async () => {
    const calls = given.capture('post', '/api/exchange/orders', f.createdOrder(), { status: 201 })
    await ExchangeApi.createOrder(f.NEW_ORDER_REQUEST)
    expect(calls).toHaveLength(1)
    expect(calls[0].body).toEqual(f.NEW_ORDER_REQUEST)
    expect(calls[0].contentType).toBe('application/json')
  })


  it('hands over the created order camelCased — the 201 is a success like any 2xx', async () => {
    const order = await ExchangeApi.createOrder(f.NEW_ORDER_REQUEST)
    expect(order).toMatchObject({
      id: f.NEW_ORDER_ID,
      status: 'awaiting_deposit',
      fromAsset: 'KNF Coin',
      toAsset: 'LTC Testnet',
      fromAmount: 10,
      depositAddress: f.createdOrder().deposit_address,
      destination: f.STUDENT_LTC,
      fromIcon: '/api/exchange/icons/knf',
      toIcon: '/api/exchange/icons/ltc4',
    })
  })
})







// -----------------------------------------------------------
// A failed request
// -----------------------------------------------------------
//
// How every call fails: with the backend's sentence word for
// word, the status when there is none, fetch's own error when
// nothing answers, a parse error for a body that is not JSON.
// -----------------------------------------------------------

describe('ExchangeApi — a failed request', () => {

  it('rejects with the backend\'s sentence, word for word', async () => {
    const tooMuch = f.rates.limits[f.KNF].max * 5
    await expect(ExchangeApi.createOrder({ ...f.NEW_ORDER_REQUEST, from_amount: tooMuch })).rejects.toHaveProperty('message', f.AMOUNT_REFUSALS[f.KNF])
    await expect(ExchangeApi.getOrder('NOPE')).rejects.toHaveProperty('message', 'Not found')
  })


  it.each([
    ['a proxy\'s HTML page', () => given.html('get', '/api/exchange/rates', 502), 'Request failed (502)'],
    ['an empty body', () => given.empty('get', '/api/exchange/rates', 500), 'Request failed (500)'],
    ['JSON without an error field', () => given.json('get', '/api/exchange/rates', { message: 'down' }, { status: 503 }), 'Request failed (503)'],
    ['an empty error sentence', () => given.error('get', '/api/exchange/rates', '', 400), 'Request failed (400)'],
  ])('names the status when the answer carries no sentence — %s', async (_, answer, message) => {
    answer()
    await expect(ExchangeApi.getRates()).rejects.toHaveProperty('message', message)
  })


  it('rejects with fetch\'s own error when nothing answers', async () => {
    given.networkError('get', '/api/exchange/rates')
    const failure = ExchangeApi.getRates()
    await expect(failure).rejects.toThrow(TypeError)
    await expect(failure).rejects.toHaveProperty('message', NETWORK_ERROR)
  })


  it('rejects a successful answer it cannot read as JSON', async () => {
    given.text('get', '/api/exchange/rates', 'OK')
    await expect(ExchangeApi.getRates()).rejects.toThrow(SyntaxError)
  })
})
