// -----------------------------------------------------------
//  [*] Tests — Exchange page: the swap form
//
//  Everything about creating an order, as the student sees
//  it:
//    - before the rates arrive: KNF Coin → LTC Testnet, nothing
//      typed, the limits loading, the rate unavailable, the
//      coins' dots in place of their logos, no estimate
//      whatever is typed
//    - the quote: the coins' logos from the rates answer, the
//      sent asset's limits and the rate in tickers, an
//      estimate of what is received as the amount is typed —
//      rounded to eight decimals, thousands grouped — and none
//      for an amount that is not one
//    - the flip: the assets, their logos, limits, rate and
//      address hint swap; the amount and any message are
//      cleared, the typed address stays
//    - the checks made before anything is sent, in their order:
//      an amount at all, within the sent asset's limits (the
//      limits themselves allowed), an address — and, with no
//      limits loaded yet, the amount left to the backend
//    - what the exchange can pay out: the maximum capped at it,
//      an amount over it refused in the backend's words before
//      anything is sent, a direction it cannot pay out at all
//      said so, and — not knowing it — the order left to the
//      backend, whose refusal (or 503) is shown as it came
//    - the submit: only the intent goes out (the assets, the
//      amount as a number, the trimmed address — never a
//      price), the button says the order is being created and
//      takes no second click, Enter submits too, success opens
//      the new order's page, and a refusal or failure is shown
//      in the words that came back (the form's own sentence
//      when none came)
//  and the backend contract of POST /api/exchange/orders as
//  the form consumes it.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { given } from '../../support/backend/server'
import { NETWORK_ERROR, describeEndpointContract, settle } from '../../support/backend/contract'
import { currentPath } from '../../support/shell/router'
import { watchRequests } from '../../support/shell/requests'
import {
  RATE_LINE, addressField, fillOrder, flipButton, panel, receiveField, renderExchange, sendField, submitButton,
} from '../../support/exchange/page'
import * as f from '../../support/backend/fixtures'
import { ExchangeApi } from '@/pages/Exchange/lib/api.js'


const NEW_ORDER_PAGE = `/exchange/order/${f.NEW_ORDER_ID}`

// The limits of each asset sent, as the rates answer them —
// every amount the checks are tried with comes from them
const KNF_LIMITS = f.rates.limits[f.KNF]
const LTC_LIMITS = f.rates.limits[f.LTC]

// The hint under the amount sent, and the form's own sentence
// for an amount outside the limits
const limitsHint = (asset, ticker) => `Min ${f.rates.limits[asset].min} · Max ${f.rates.limits[asset].max} ${ticker}`
const outsideTheLimits = (asset) => `Amount must be between ${f.rates.limits[asset].min} and ${f.rates.limits[asset].max} ${asset}`

// The page with its rates in, ready to quote
const renderQuoting = async () => {
  const view = renderExchange()
  await screen.findByText(RATE_LINE)
  return view
}

// The POSTs that left the page
const posts = (seen) => seen.filter((request) => request === 'POST /api/exchange/orders')

// The coin logo a panel's chip shows, by the URL it was drawn
// from — nothing while the coin wears its dot
const logoOf = (element) => element.querySelector('img')?.getAttribute('src') ?? null







// -----------------------------------------------------------
// Before the rates arrive
// -----------------------------------------------------------
//
// The form before the backend has answered: the default
// direction, the limits loading, no rate and no estimate.
// -----------------------------------------------------------

describe('Swap form — before the rates arrive', () => {

  it('starts as KNF Coin → LTC Testnet, with nothing typed', () => {
    given.hang('get', '/api/exchange/rates')
    renderExchange()

    expect(within(panel('You send')).getByText('KNF Coin')).toBeInTheDocument()
    expect(within(panel('You receive')).getByText('LTC Testnet')).toBeInTheDocument()
    expect(sendField()).toHaveValue('')
    expect(receiveField()).toHaveValue('')
    expect(addressField()).toHaveValue('')
    expect(addressField()).toHaveAttribute('placeholder', 'Your LTC Testnet address (tltc1...)')
    expect(submitButton()).toHaveTextContent(/^Exchange now$/)
    expect(submitButton()).toBeEnabled()
  })


  it('shows each coin\'s dot until the rates bring the logos', () => {
    given.hang('get', '/api/exchange/rates')
    renderExchange()

    for (const label of ['You send', 'You receive']) {
      expect(logoOf(panel(label)), label).toBeNull()
      expect(panel(label).querySelector('span[style*="background-color"]'), label).not.toBeNull()
    }
  })


  it('says the limits are loading and the rate is unavailable', () => {
    given.hang('get', '/api/exchange/rates')
    renderExchange()

    expect(within(panel('You send')).getByText('Loading limits...')).toBeInTheDocument()
    expect(within(panel('You receive')).getByText('Rate unavailable')).toBeInTheDocument()
  })


  it('estimates nothing without a rate, whatever is typed', async () => {
    given.hang('get', '/api/exchange/rates')
    const { user } = renderExchange()

    await user.type(sendField(), '10')

    expect(receiveField()).toHaveValue('')
  })


  it('the estimate cannot be typed into', async () => {
    const { user } = await renderQuoting()

    expect(receiveField()).toHaveAttribute('readonly')
    await user.type(receiveField(), '5')
    expect(receiveField()).toHaveValue('')
  })
})







// -----------------------------------------------------------
// The quote
// -----------------------------------------------------------
//
// The limits and the rate in tickers, and the estimate
// following the amount as the student types.
// -----------------------------------------------------------

describe('Swap form — the quote', () => {

  it('shows the limits of the asset sent and the rate, both in tickers', async () => {
    await renderQuoting()

    expect(within(panel('You send')).getByText(limitsHint(f.KNF, 'KNF'))).toBeInTheDocument()
    expect(within(panel('You receive')).getByText(RATE_LINE)).toBeInTheDocument()
  })


  it('shows each coin with the logo the rates answer advertises', async () => {
    await renderQuoting()

    expect(logoOf(panel('You send'))).toBe(f.ICONS[f.KNF])
    expect(logoOf(panel('You receive'))).toBe(f.ICONS[f.LTC])
  })


  it('a coin the rates answer has no logo for wears its dot', async () => {
    given.json('get', '/api/exchange/rates', { ...f.rates, icons: { [f.KNF]: f.ICONS[f.KNF], [f.LTC]: null } })
    await renderQuoting()

    expect(logoOf(panel('You send'))).toBe(f.ICONS[f.KNF])
    expect(logoOf(panel('You receive'))).toBeNull()
  })


  it('estimates what the student receives as they type', async () => {
    const { user } = await renderQuoting()

    await user.type(sendField(), '10')

    expect(receiveField()).toHaveValue('1.2345678')
  })


  it('rounds the estimate to eight decimals', async () => {
    const { user } = await renderQuoting()

    await user.type(sendField(), '0.123')

    expect(receiveField()).toHaveValue('0.01518518')
  })


  it('groups thousands in the estimate', async () => {
    const { user } = await renderQuoting()

    await user.type(sendField(), '20000')

    expect(receiveField()).toHaveValue('2,469.1356')
  })


  it('estimates an amount beyond the limits too — they are checked on submit', async () => {
    const { user } = await renderQuoting()

    await user.type(sendField(), `${KNF_LIMITS.max * 2}`)

    expect(receiveField()).not.toHaveValue('')
    expect(screen.queryByText(outsideTheLimits(f.KNF))).toBeNull()
  })


  it.each([
    ['letters', 'abc'],
    ['zero', '0'],
    ['a negative amount', '-5'],
  ])('estimates nothing for %s', async (_, amount) => {
    const { user } = await renderQuoting()

    await user.type(sendField(), amount)

    expect(receiveField()).toHaveValue('')
  })
})







// -----------------------------------------------------------
// Flipping the direction
// -----------------------------------------------------------
//
// The flip button swaps the assets, the limits, the rate and
// the address hint, starts the amount over and keeps the
// address.
// -----------------------------------------------------------

describe('Swap form — flipping the direction', () => {

  it('swaps the assets, their logos, the limits, the rate and the address hint', async () => {
    const { user } = await renderQuoting()

    await user.click(flipButton())

    expect(within(panel('You send')).getByText('LTC Testnet')).toBeInTheDocument()
    expect(within(panel('You receive')).getByText('KNF Coin')).toBeInTheDocument()
    expect(logoOf(panel('You send'))).toBe(f.ICONS[f.LTC])
    expect(logoOf(panel('You receive'))).toBe(f.ICONS[f.KNF])
    expect(within(panel('You send')).getByText(limitsHint(f.LTC, 'tLTC4'))).toBeInTheDocument()
    expect(within(panel('You receive')).getByText('1 tLTC4 ≈ 8.10000066 KNF')).toBeInTheDocument()
    expect(addressField()).toHaveAttribute('placeholder', 'Your KNF Coin address (knf1...)')
  })


  it('estimates in the new direction', async () => {
    const { user } = await renderQuoting()

    await user.click(flipButton())
    await user.type(sendField(), '1')

    expect(receiveField()).toHaveValue('8.10000066')
  })


  it('clears the amount and any message, and keeps the typed address', async () => {
    const { user } = await renderQuoting()
    await fillOrder(user, '', f.STUDENT_LTC)
    expect(screen.getByText('Enter a valid amount')).toBeInTheDocument()
    await user.type(sendField(), '5')

    await user.click(flipButton())

    expect(sendField()).toHaveValue('')
    expect(receiveField()).toHaveValue('')
    expect(screen.queryByText('Enter a valid amount')).toBeNull()
    expect(addressField()).toHaveValue(f.STUDENT_LTC)
  })


  it('flipping twice comes back to KNF Coin → LTC Testnet', async () => {
    const { user } = await renderQuoting()

    await user.click(flipButton())
    await user.click(flipButton())

    expect(within(panel('You send')).getByText('KNF Coin')).toBeInTheDocument()
    expect(within(panel('You receive')).getByText(RATE_LINE)).toBeInTheDocument()
    expect(addressField()).toHaveAttribute('placeholder', 'Your LTC Testnet address (tltc1...)')
  })
})







// -----------------------------------------------------------
// The checks before anything is sent
// -----------------------------------------------------------
//
// The form's own checks — a valid amount, within the limits,
// an address — in that order, each with its sentence, nothing
// sent until they pass.
// -----------------------------------------------------------

describe('Swap form — the checks before anything is sent', () => {

  it.each([
    ['nothing', ''],
    ['letters', 'abc'],
    ['zero', '0'],
    ['a negative amount', '-1'],
  ])('with %s for an amount: "Enter a valid amount", and nothing is sent', async (_, amount) => {
    const { user } = await renderQuoting()
    const seen = watchRequests()

    await fillOrder(user, amount, f.STUDENT_LTC)

    expect(screen.getByText('Enter a valid amount')).toBeInTheDocument()
    await settle()
    expect(posts(seen)).toEqual([])
  })


  it.each([
    ['under the minimum', `${KNF_LIMITS.min / 2}`],
    ['over the maximum', `${KNF_LIMITS.max + 0.5}`],
  ])('an amount %s names the limits of the asset sent', async (_, amount) => {
    const { user } = await renderQuoting()
    const seen = watchRequests()

    await fillOrder(user, amount, f.STUDENT_LTC)

    expect(screen.getByText(outsideTheLimits(f.KNF))).toBeInTheDocument()
    await settle()
    expect(posts(seen)).toEqual([])
  })


  it('after a flip, the limits are those of LTC Testnet', async () => {
    const { user } = await renderQuoting()
    await user.click(flipButton())

    await fillOrder(user, `${LTC_LIMITS.max * 1.5}`, f.STUDENT_KNF)

    expect(screen.getByText(outsideTheLimits(f.LTC))).toBeInTheDocument()
  })


  it.each([
    ['the minimum', `${KNF_LIMITS.min}`],
    ['the maximum', `${KNF_LIMITS.max}`],
  ])('%s itself is allowed', async (_, amount) => {
    const calls = given.capture('post', '/api/exchange/orders', ({ body }) => f.createdOrder(body), { status: 201 })
    const { user } = await renderQuoting()

    await fillOrder(user, amount, f.STUDENT_LTC)

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.from_amount).toBe(Number(amount))
  })


  it.each([
    ['no address', ''],
    ['a blank one', '   '],
  ])('with %s, asks for the address of the asset received', async (_, address) => {
    const { user } = await renderQuoting()

    await fillOrder(user, '10', address)

    expect(screen.getByText('Enter your LTC Testnet address')).toBeInTheDocument()
  })


  it('after a flip, asks for the KNF Coin address', async () => {
    const { user } = await renderQuoting()
    await user.click(flipButton())

    await fillOrder(user, '1', '')

    expect(screen.getByText('Enter your KNF Coin address')).toBeInTheDocument()
  })


  it('checks the amount first, then its limits, then the address', async () => {
    const { user } = await renderQuoting()

    await user.click(submitButton())
    expect(screen.getByText('Enter a valid amount')).toBeInTheDocument()

    await user.type(sendField(), `${KNF_LIMITS.max * 5}`)
    await user.click(submitButton())
    expect(screen.getByText(outsideTheLimits(f.KNF))).toBeInTheDocument()

    await user.clear(sendField())
    await user.type(sendField(), '10')
    await user.click(submitButton())
    expect(screen.getByText('Enter your LTC Testnet address')).toBeInTheDocument()
    expect(screen.queryByText('Enter a valid amount')).toBeNull()
  })


  it('with no limits loaded yet, leaves the amount to the backend — and shows its refusal', async () => {
    given.hang('get', '/api/exchange/rates')
    const { user } = renderExchange()

    await fillOrder(user, `${KNF_LIMITS.max * 5}`, f.STUDENT_LTC)

    expect(await screen.findByText(f.AMOUNT_REFUSALS[f.KNF])).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// What the exchange can pay out
// -----------------------------------------------------------
//
// The rates say how much of each asset the exchange can still
// pay out: the form caps the maximum at it and refuses more
// in the backend's own words, before anything is sent.
// -----------------------------------------------------------

describe('Swap form — what the exchange can pay out', () => {

  // The rates, the exchange able to pay out only `ltc` tLTC4 (null: not known)
  const payingOut = (ltc) => given.json('get', '/api/exchange/rates', { ...f.rates, capacity: { ...f.rates.capacity, [f.LTC]: ltc } })


  it('caps the maximum at what 40 tLTC4 can pay for, rounded down to the satoshi', async () => {
    payingOut(40)
    await renderQuoting()

    expect(within(panel('You send')).getByText(`Min ${KNF_LIMITS.min} · Max 324.00002656 KNF`)).toBeInTheDocument()
  })


  it('refuses more than that before anything is sent, in the backend\'s words', async () => {
    payingOut(40)
    const { user } = await renderQuoting()
    const seen = watchRequests()

    await fillOrder(user, '324.00002657', f.STUDENT_LTC)

    expect(screen.getByText(f.capacityRefusal('324.00002656', f.KNF))).toBeInTheDocument()
    await settle()
    expect(posts(seen)).toEqual([])
  })


  it('takes the most it can pay for', async () => {
    payingOut(40)
    const calls = given.capture('post', '/api/exchange/orders', ({ body }) => f.createdOrder(body), { status: 201 })
    const { user } = await renderQuoting()

    await fillOrder(user, '324.00002656', f.STUDENT_LTC)

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body.from_amount).toBe(324.00002656)
  })


  it('says so when it cannot pay out even the smallest order', async () => {
    payingOut(0.0001)
    const { user } = await renderQuoting()
    const seen = watchRequests()

    expect(within(panel('You send')).getByText('The exchange cannot pay out tLTC4 right now')).toBeInTheDocument()
    await fillOrder(user, `${KNF_LIMITS.min}`, f.STUDENT_LTC)

    expect(screen.getByText(f.cannotPayOut(f.LTC))).toBeInTheDocument()
    await settle()
    expect(posts(seen)).toEqual([])
  })


  it('after a flip, what can be paid out of KNF Coin applies', async () => {
    given.json('get', '/api/exchange/rates', { ...f.rates, capacity: { ...f.rates.capacity, [f.KNF]: 5 } })
    const { user } = await renderQuoting()
    expect(within(panel('You send')).getByText(limitsHint(f.KNF, 'KNF'))).toBeInTheDocument()

    await user.click(flipButton())

    expect(within(panel('You send')).getByText(`Min ${LTC_LIMITS.min} · Max 0.6172839 tLTC4`)).toBeInTheDocument()
  })


  it('not knowing what can be paid out, leaves it to the backend — and shows its refusal', async () => {
    payingOut(null)
    given.error('post', '/api/exchange/orders', f.capacityRefusal('8.09988645', f.KNF))
    const { user } = await renderQuoting()
    expect(within(panel('You send')).getByText(limitsHint(f.KNF, 'KNF'))).toBeInTheDocument()

    await fillOrder(user, `${KNF_LIMITS.max}`, f.STUDENT_LTC)

    expect(await screen.findByText(f.capacityRefusal('8.09988645', f.KNF))).toBeInTheDocument()
  })


  it('a reserve the backend cannot read right now: its 503 sentence is shown', async () => {
    given.error('post', '/api/exchange/orders', f.reserveUnreadable(f.LTC), 503)
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.STUDENT_LTC)

    expect(await screen.findByText(f.reserveUnreadable(f.LTC))).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// Creating the order
// -----------------------------------------------------------
//
// The submit: only the intent sent, the new order's page
// opened, a refusal shown in the backend's words, no second
// order while the first is on its way.
// -----------------------------------------------------------

describe('Swap form — creating the order', () => {

  it('sends the intent only — the assets, the amount as a number and the trimmed address, never a price', async () => {
    const calls = given.capture('post', '/api/exchange/orders', ({ body }) => f.createdOrder(body), { status: 201 })
    const { user } = await renderQuoting()

    await fillOrder(user, '10', `  ${f.STUDENT_LTC}  `)

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ from_asset: 'KNF Coin', to_asset: 'LTC Testnet', from_amount: 10, destination: f.STUDENT_LTC })
    expect(calls[0].contentType).toBe('application/json')
  })


  it('after a flip, sends the other direction', async () => {
    const calls = given.capture('post', '/api/exchange/orders', ({ body }) => f.createdOrder(body), { status: 201 })
    const { user } = await renderQuoting()
    await user.click(flipButton())

    await fillOrder(user, '0.5', f.STUDENT_KNF)

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0].body).toEqual({ from_asset: 'LTC Testnet', to_asset: 'KNF Coin', from_amount: 0.5, destination: f.STUDENT_KNF })
  })


  it('opens the new order\'s page', async () => {
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.STUDENT_LTC)

    await waitFor(() => expect(currentPath()).toBe(NEW_ORDER_PAGE))
  })


  it('says the order is being created, and takes no second click meanwhile', async () => {
    given.hang('post', '/api/exchange/orders')
    const seen = watchRequests()
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.STUDENT_LTC)

    expect(await screen.findByRole('button', { name: 'Creating order...' })).toBeDisabled()
    await user.click(submitButton())
    await settle(50)
    expect(posts(seen)).toHaveLength(1)
  })


  it('pressing Enter in the address field submits as well', async () => {
    const { user } = await renderQuoting()

    await user.type(sendField(), '10')
    await user.type(addressField(), `${f.STUDENT_LTC}{Enter}`)

    await waitFor(() => expect(currentPath()).toBe(NEW_ORDER_PAGE))
  })


  it('shows the backend\'s refusal word for word, and lets the student try again', async () => {
    const { user } = await renderQuoting()

    await fillOrder(user, '10', 'tltc1qnotanaddress')

    expect(await screen.findByText(f.invalidDestination(f.LTC))).toBeInTheDocument()
    expect(submitButton()).toHaveTextContent(/^Exchange now$/)
    expect(submitButton()).toBeEnabled()
    expect(currentPath()).toBe('/exchange')
  })


  it('refuses one of the exchange\'s own addresses as the destination, in the backend\'s words', async () => {
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.RESERVE_LTC)

    expect(await screen.findByText(f.EXCHANGE_ADDRESS_REFUSAL)).toBeInTheDocument()
  })


  it('a new attempt clears the old message first', async () => {
    const { user } = await renderQuoting()
    await fillOrder(user, '10', f.RESERVE_LTC)
    await screen.findByText(f.EXCHANGE_ADDRESS_REFUSAL)

    await user.clear(addressField())
    await fillOrder(user, '', f.STUDENT_LTC)

    await waitFor(() => expect(currentPath()).toBe(NEW_ORDER_PAGE))
    expect(screen.queryByText(f.EXCHANGE_ADDRESS_REFUSAL)).toBeNull()
  })


  it.each([
    ['a proxy\'s HTML page names the status', () => given.html('post', '/api/exchange/orders', 502), 'Request failed (502)'],
    ['a dropped connection says what fetch said', () => given.networkError('post', '/api/exchange/orders'), NETWORK_ERROR],
    ['the backend\'s own failure is shown as it is', () => given.error('post', '/api/exchange/orders', f.CREATE_FAILURE, 500), f.CREATE_FAILURE],
  ])('a failure without a refusal: %s', async (_, answer, message) => {
    answer()
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.STUDENT_LTC)

    expect(await screen.findByText(message)).toBeInTheDocument()
    expect(submitButton()).toBeEnabled()
  })


  it('a failure that comes without words falls back to the form\'s own sentence', async () => {
    // No answer of the backend makes ExchangeApi fail without
    // naming a reason, so ExchangeApi itself fails silently here
    vi.spyOn(ExchangeApi, 'createOrder').mockRejectedValue(new Error(''))
    const { user } = await renderQuoting()

    await fillOrder(user, '10', f.STUDENT_LTC)

    expect(await screen.findByText('Could not create the order')).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// Backend contract — POST /api/exchange/orders on the form
// -----------------------------------------------------------
//
// The request goes out on submit, with the rates in. Loaded:
// the new order's page opens. A failure: the words that came
// back, under the form. In flight: the button says the order
// is being created and is disabled. Whatever the body: no
// crash, the form stands.
// -----------------------------------------------------------

describeEndpointContract({
  path: '/api/exchange/orders',
  method: 'post',
  fixture: f.createdOrder(),
  render: async () => {
    const { user } = await renderQuoting()
    await fillOrder(user, '10', f.STUDENT_LTC)
  },
  chrome: () => screen.getByRole('heading', { level: 1, name: 'Swap testnet coins' }) && sendField(),
  loaded: async () => {
    await waitFor(() => expect(currentPath()).toBe(NEW_ORDER_PAGE))
  },
  failed: async (says) => {
    expect(await screen.findByText(says)).toBeInTheDocument()
    expect(submitButton()).toBeEnabled()
  },
  loading: () => screen.queryByRole('button', { name: 'Creating order...' })?.disabled,
})
