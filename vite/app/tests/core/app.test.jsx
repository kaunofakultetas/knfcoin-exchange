// -----------------------------------------------------------
//  [*] Tests — App.jsx (the shell, the routes, the history)
//
//  The whole application through renderApp — App.jsx inside
//  the BrowserRouter main.jsx gives it, started at a route:
//    - the shell every page renders inside (the shared
//      Layout): the banner with the brand and the navigation,
//      the page as the main landmark, the footer — once each,
//      in that order, on every page
//    - the route table: each route's page, an order page for
//      the id in the path, the path's case and trailing slash
//      ignored, anything else sent home with a replace (Back
//      never returns to the unknown address)
//    - moving around: the header's pills and brand, the
//      explorer left to the browser, Back, an order row and
//      the way back from an order, the home page's call to
//      action
//    - a swap from start to finish: the form on /exchange to
//      the new order's page, or the backend's refusal
//    - the same App under StrictMode, as main.jsx mounts it:
//      it boots and navigates, an order page ignores the late
//      answer of the effect StrictMode discarded, and polls
//      once per interval, not twice
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { StrictMode } from 'react'
import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter } from 'react-router-dom'
import { http, HttpResponse, delay } from 'msw'
import { renderApp } from '../support/render'
import { server, url } from '../support/backend/server'
import { followedByTheBrowser, goBack, navigateTo } from '../support/shell/router'
import { watchRequests } from '../support/shell/requests'
import { wholeText } from '../support/regions'
import * as f from '../support/backend/fixtures'
import App from '@/App.jsx'


// The headline of each page, as the student reads it
const HOME = 'Learn crypto by actually trading it'
const EXCHANGE = 'Swap testnet coins'
const RESERVES = 'Exchange reserves'
const orderTitle = (id) => `Order #${id}`

const main = () => screen.getByRole('main')
const banner = () => screen.getByRole('banner')
const pill = (name) => within(within(banner()).getByRole('navigation')).getByRole('link', { name })
const brand = () => within(banner()).getByRole('link', { name: /KNF Exchange$/ })

const pageTitled = (text) => within(main()).findByRole('heading', { level: 1, name: wholeText(text) })

const landsOn = async (path) => {
  await waitFor(() => expect(window.location.pathname).toBe(path))
}

// DOM order is reading order: a before b
const precedes = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

// The live rate line, on the home page's chip and under the
// swap form's estimate alike
const RATE_LINE = '1 KNF ≈ 0.12345678 tLTC4'

const PAGES = [
  ['/', HOME],
  ['/exchange', EXCHANGE],
  [`/exchange/order/${f.COMPLETED_ID}`, orderTitle(f.COMPLETED_ID)],
  ['/reserves', RESERVES],
]







// -----------------------------------------------------------
// The shell
// -----------------------------------------------------------
//
// Every page in the shared frame — the banner, the page as
// the main landmark, the footer — once each, in that order.
// -----------------------------------------------------------

describe('App shell', () => {

  it.each(PAGES)('%s sits in the shared frame: the banner, the page as the main landmark, the footer — once each, in that order', async (route, title) => {
    renderApp({ route })
    expect(await pageTitled(title)).toBeInTheDocument()

    expect(within(banner()).getByRole('navigation')).toBeInTheDocument()
    expect(brand()).toBeInTheDocument()
    expect(precedes(banner(), main())).toBe(true)
    expect(precedes(main(), screen.getByRole('contentinfo'))).toBe(true)
    for (const role of ['banner', 'navigation', 'main', 'contentinfo']) {
      expect(screen.getAllByRole(role), role).toHaveLength(1)
    }
  })
})







// -----------------------------------------------------------
// The routes
// -----------------------------------------------------------
//
// Which page each path opens: the order an order page's path
// names, a path's case and trailing slash ignored, anything
// unknown sent home — replaced, so Back skips it.
// -----------------------------------------------------------

describe('App routes', () => {

  it('an order page shows the order named in the path, and asks the backend for that one', async () => {
    const seen = watchRequests()
    renderApp({ route: `/exchange/order/${f.CONFIRMING_ID}` })

    expect(await pageTitled(orderTitle(f.CONFIRMING_ID))).toBeInTheDocument()
    expect(seen).toContain(`GET /api/exchange/orders/${f.CONFIRMING_ID}`)
  })


  it.each([
    ['/exchange/', EXCHANGE],
    ['/RESERVES', RESERVES],
  ])('the case and a trailing slash do not matter: %s opens its page', async (route, title) => {
    renderApp({ route })
    expect(await pageTitled(title)).toBeInTheDocument()
  })


  it.each([
    ['a path nobody routes', '/nieko'],
    ['an order address without an id', '/exchange/order'],
    ['extra segments under an order', `/exchange/order/${f.COMPLETED_ID}/extra`],
    ['extra segments under the reserves', '/reserves/knf'],
  ])('%s (%s) is sent home', async (_, route) => {
    renderApp({ route })
    await landsOn('/')
    expect(await pageTitled(HOME)).toBeInTheDocument()
  })


  it('an unknown address is replaced, not kept — Back skips it', async () => {
    renderApp({ route: '/reserves' })
    await pageTitled(RESERVES)

    await navigateTo('/nieko')
    await landsOn('/')
    await pageTitled(HOME)

    await goBack()
    await landsOn('/reserves')
    expect(await pageTitled(RESERVES)).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// Moving around
// -----------------------------------------------------------
//
// Getting from page to page: the pills and the brand inside
// the app, the Explorer left to the browser, Back walking the
// visits in reverse, the links between the home page, the
// exchange and its orders.
// -----------------------------------------------------------

describe('App navigation', () => {

  it('the pills move between the pages inside the app', async () => {
    const { user } = renderApp({ route: '/' })
    await pageTitled(HOME)

    await user.click(pill('Exchange'))
    await landsOn('/exchange')
    expect(await pageTitled(EXCHANGE)).toBeInTheDocument()

    await user.click(pill('Reserves'))
    await landsOn('/reserves')
    expect(await pageTitled(RESERVES)).toBeInTheDocument()

    await user.click(pill('Home'))
    await landsOn('/')
    expect(await pageTitled(HOME)).toBeInTheDocument()
  })


  it('the brand leads home from any page', async () => {
    const { user } = renderApp({ route: '/reserves' })
    await pageTitled(RESERVES)

    await user.click(brand())
    await landsOn('/')
    expect(await pageTitled(HOME)).toBeInTheDocument()
  })


  it('the Explorer pill is left to the browser — Caddy serves the explorer outside the app', async () => {
    renderApp({ route: '/exchange' })
    await pageTitled(EXCHANGE)

    expect(pill('Explorer')).toHaveAttribute('href', '/explorer/')
    expect(followedByTheBrowser(pill('Explorer'))).toBe(true)
    expect(window.location.pathname).toBe('/exchange')
  })


  it('Back walks the pages the student visited, in reverse', async () => {
    const { user } = renderApp({ route: '/' })
    await pageTitled(HOME)
    await user.click(pill('Exchange'))
    await pageTitled(EXCHANGE)
    await user.click(pill('Reserves'))
    await pageTitled(RESERVES)

    await goBack()
    await landsOn('/exchange')
    expect(await pageTitled(EXCHANGE)).toBeInTheDocument()

    await goBack()
    await landsOn('/')
    expect(await pageTitled(HOME)).toBeInTheDocument()
  })


  it('an order row on the exchange opens that order, and the arrow back returns to the form', async () => {
    const { user } = renderApp({ route: '/exchange' })
    const row = await within(main()).findByRole('link', { name: new RegExp(`#${f.SENDING_ID}`) })

    await user.click(row)
    await landsOn(`/exchange/order/${f.SENDING_ID}`)
    expect(await pageTitled(orderTitle(f.SENDING_ID))).toBeInTheDocument()

    await user.click(within(main()).getByRole('link', { name: 'Back to Exchange' }))
    await landsOn('/exchange')
    expect(await pageTitled(EXCHANGE)).toBeInTheDocument()
  })


  it('"Start swapping" on the home page opens the exchange', async () => {
    const { user } = renderApp({ route: '/' })
    await user.click(await within(main()).findByRole('link', { name: 'Start swapping' }))
    await landsOn('/exchange')
    expect(await pageTitled(EXCHANGE)).toBeInTheDocument()
  })
})







// -----------------------------------------------------------
// A swap from start to finish
// -----------------------------------------------------------
//
// The whole journey through the real App: the form creates an
// order and lands on its page asking for the deposit — or
// keeps the student on the form with the backend's refusal.
// -----------------------------------------------------------

describe('App — a swap from start to finish', () => {

  const fillAndSubmit = async (user, amount, destination) => {
    await within(main()).findByText(RATE_LINE)
    await user.type(within(main()).getAllByPlaceholderText('0.00000000')[0], amount)
    await user.type(within(main()).getByPlaceholderText('Your LTC Testnet address (tltc1...)'), destination)
    await user.click(within(main()).getByRole('button', { name: 'Exchange now' }))
  }


  it('the form creates the order and lands on its page, which asks the student to pay', async () => {
    const { user } = renderApp({ route: '/exchange' })
    await fillAndSubmit(user, '10', f.STUDENT_LTC)

    await landsOn(`/exchange/order/${f.NEW_ORDER_ID}`)
    expect(await pageTitled(orderTitle(f.NEW_ORDER_ID))).toBeInTheDocument()
    expect(within(main()).getByText(wholeText('Send 10 KNF Coin to this address:'))).toBeInTheDocument()
    expect(within(main()).getByText(f.createdOrder().deposit_address)).toBeInTheDocument()
    expect(within(main()).getAllByText('Awaiting deposit').length).toBeGreaterThan(0)
  })


  it('a refused order keeps the student on the form, with the backend\'s sentence', async () => {
    const { user } = renderApp({ route: '/exchange' })
    await fillAndSubmit(user, '10', f.RESERVE_LTC)

    expect(await within(main()).findByText(f.EXCHANGE_ADDRESS_REFUSAL)).toBeInTheDocument()
    expect(window.location.pathname).toBe('/exchange')
  })
})







// -----------------------------------------------------------
// As main.jsx mounts it
// -----------------------------------------------------------
//
// Production wraps the App in StrictMode: in development every
// effect runs, is cleaned up and runs again. renderApp leaves
// it out; here the App boots and navigates under it, and the
// order page's effect proves it cleans up after itself.
// -----------------------------------------------------------

describe('App under StrictMode, as main.jsx mounts it', () => {

  const renderStrictApp = (route) => {
    window.history.replaceState(null, '', route)
    const user = userEvent.setup()
    const view = render(
      <StrictMode>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </StrictMode>
    )
    return { user, ...view }
  }


  it('boots: "/" shows the home page with the live rate', async () => {
    renderStrictApp('/')
    expect(await pageTitled(HOME)).toBeInTheDocument()
    expect(await within(main()).findByText(RATE_LINE)).toBeInTheDocument()
  })


  it('navigates: the pills lead to the exchange and the reserves', async () => {
    const { user } = renderStrictApp('/')
    await pageTitled(HOME)

    await user.click(pill('Exchange'))
    expect(await pageTitled(EXCHANGE)).toBeInTheDocument()
    await user.click(pill('Reserves'))
    expect(await within(main()).findByText(f.RESERVE_KNF)).toBeInTheDocument()
  })


  it('an order page ignores the late answer of the effect StrictMode discarded', async () => {
    // The discarded effect's request answers last, with an
    // older state of the order — from before its payout
    // failed — and must not overwrite the answer of the effect
    // that stayed
    const note = f.PAYOUT_PENDING
    let calls = 0
    server.use(http.get(url(`/api/exchange/orders/${f.SENDING_ID}`), async () => {
      calls += 1
      if (calls === 1) {
        await delay(150)
        return HttpResponse.json({ ...f.orderById(f.SENDING_ID), error: null })
      }
      return HttpResponse.json(f.orderById(f.SENDING_ID))
    }))
    renderStrictApp(`/exchange/order/${f.SENDING_ID}`)

    expect(await within(main()).findByText(note)).toBeInTheDocument()
    await act(async () => { await delay(300) })
    expect(calls).toBe(2)
    expect(within(main()).getByText(note)).toBeInTheDocument()
  })


  it('an order page polls once per interval — the discarded effect\'s timer is cleared', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const seen = watchRequests(`/api/exchange/orders/${f.AWAITING_ID}`)
    renderStrictApp(`/exchange/order/${f.AWAITING_ID}`)
    await pageTitled(orderTitle(f.AWAITING_ID))
    expect(seen).toHaveLength(2)

    await act(async () => { vi.advanceTimersByTime(2000) })
    await act(async () => { await delay(100) })
    expect(seen).toHaveLength(3)
  })
})
