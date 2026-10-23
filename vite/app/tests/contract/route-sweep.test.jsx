// -----------------------------------------------------------
//  [*] Tests — the route sweep (every route × every backend state)
//
//  Every route of App.jsx, with real ids from the fixtures,
//  rendered through the real App (renderApp) under the
//  conditions every page must tolerate whatever it does
//  inside:
//
//    - the default backend — the route lands where it should
//      (anything unknown on the home page), renders its page,
//      and asks exactly what it needs (setup.js fails the test
//      on any request the double does not know); its new-tab
//      links cannot reach back into the app, its images say
//      what they are
//    - every /api GET answering 500 with the backend's error
//      body — the page shows ITS failure (the backend's own
//      sentence where the page passes it on), nothing crashes
//    - every /api GET answering a JSON string — an answer of
//      the wrong shape: nothing crashes
//    - every /api GET dropping the connection — like the 500,
//      with fetch's own words where the page passes them on
//
//  In every state the header with its navigation, the main
//  landmark and the footer stand. The per-page tests cover
//  behaviour; this file is the safety net no route can be
//  forgotten by — its first test checks it covers every route
//  App.jsx declares.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, waitFor, within } from '@testing-library/react'
import { HttpResponse } from 'msw'
import { renderApp } from '../support/render'
import { apiError } from '../support/backend/server'
import { NETWORK_ERROR, expectNoCrash, settle } from '../support/backend/contract'
import { backendIdle, everyGet, watchRequests } from '../support/shell/requests'
import { appRoutes } from '../support/shell/source'
import { wholeText } from '../support/regions'
import * as f from '../support/backend/fixtures'


// The sentence every failing GET carries in the 500 mode
const MESSAGE = 'Internal server error'

const main = () => screen.getByRole('main')

// What shows a route rendered, and how it shows a failure
const heading = (name) => () => within(main()).findByRole('heading', { level: 1, name: wholeText(name) })
const text = (words) => within(main()).findByText(words)







// -----------------------------------------------------------
// ROUTES
// -----------------------------------------------------------
//
// Every route to sweep:
//
//   path   — where the student starts
//   lands  — where the App takes them (the path itself unless
//            given)
//   shows  — finds what proves the page rendered
//   asks   — the requests the page makes under the default
//            backend, each kind once however often it polls
//   failed — given the failure's words — the backend's
//            sentence (500 mode) or fetch's (connection
//            dropped) — finds how the page presents a failed
//            read. None: the page tells nothing of it and
//            simply still shows
// -----------------------------------------------------------

const HOME = {
  lands: '/',
  shows: heading('Learn crypto by actually trading it'),
  asks: ['GET /api/exchange/rates'],
}

const ROUTES = [
  { path: '/', ...HOME },
  {
    path: '/exchange',
    shows: heading('Swap testnet coins'),
    asks: ['GET /api/exchange/orders', 'GET /api/exchange/rates'],
    failed: () => text('Rate unavailable'),
  },
  {
    path: `/exchange/order/${f.COMPLETED_ID}`,
    shows: heading(`Order #${f.COMPLETED_ID}`),
    asks: [`GET /api/exchange/orders/${f.COMPLETED_ID}`],
    failed: async (message) => {
      await heading('Order not found')()
      return text(message)
    },
  },
  {
    path: '/reserves',
    shows: heading('Exchange reserves'),
    asks: ['GET /api/exchange/reserves'],
    failed: (message) => text(message),
  },
  { path: '/nieko/nera', ...HOME },
  { path: '/exchange/order', ...HOME },
  { path: `/exchange/order/${f.COMPLETED_ID}/extra`, ...HOME },
]







// -----------------------------------------------------------
// Assertions shared by the states
// -----------------------------------------------------------
//
// What every state of the sweep checks on a route: the frame
// still standing, safe markup, the route landed on, a failure
// shown the way the page presents it.
// -----------------------------------------------------------

// The frame around every page: the header with its
// navigation, the main landmark, the footer
const expectChrome = () => {
  expect(within(screen.getByRole('banner')).getByRole('navigation')).toBeInTheDocument()
  expect(main()).toBeInTheDocument()
  expect(screen.getByRole('contentinfo')).toBeInTheDocument()
}

// New-tab links cannot reach back into the app (noreferrer
// implies noopener), images say what they are
const expectSafeMarkup = () => {
  for (const link of document.querySelectorAll('a[target="_blank"]')) {
    expect(link.getAttribute('rel') ?? '', link.getAttribute('href')).toMatch(/\bnoopener\b|\bnoreferrer\b/)
  }
  for (const image of document.querySelectorAll('img')) {
    expect(image.hasAttribute('alt'), image.getAttribute('src')).toBe(true)
  }
}

const landsOn = async (path) => {
  await waitFor(() => expect(window.location.pathname).toBe(path))
}

// A failure mode: every GET answers `respond`; the route is
// rendered and the backend let go idle
const renderFailing = async (path, respond) => {
  const gets = everyGet(respond)
  renderApp({ route: path })
  await backendIdle(gets)
  return gets
}

// What a failed read looks like on this route: its own
// presentation, or the page simply still there
const expectFailureShown = async (route, message) => {
  await landsOn(route.lands ?? route.path)
  expect(await (route.failed ? route.failed(message) : route.shows())).toBeInTheDocument()
}







// -----------------------------------------------------------
// The sweep
// -----------------------------------------------------------
//
// Every route of App.jsx under each backend state in turn:
// the default answers, a 500 with the backend's sentence, an
// answer of the wrong shape, a dropped connection.
// -----------------------------------------------------------

describe('route sweep', () => {

  it('covers every route App.jsx declares', () => {
    const redirected = (route) => (route.lands ?? route.path) !== route.path
    const swept = ROUTES.filter((route) => !redirected(route)).map((route) => route.path)
    const uncovered = appRoutes()
      .filter((route) => route.element)
      .filter((route) => {
        if (route.path === '*') return !ROUTES.some(redirected)
        const pattern = new RegExp(`^${route.path.replace(/:\w+/g, '[^/]+')}$`)
        return !swept.some((path) => pattern.test(path))
      })
      .map((route) => route.path)
    expect(uncovered).toEqual([])
  })


  describe.each(ROUTES)('$path', (route) => {

    it('renders under the default backend, and asks exactly what the page needs', async () => {
      const seen = watchRequests()
      renderApp({ route: route.path })
      await landsOn(route.lands ?? route.path)
      expect(await route.shows()).toBeInTheDocument()
      await settle(100)
      expectNoCrash()
      expectChrome()
      expectSafeMarkup()
      expect([...new Set(seen)].sort()).toEqual(route.asks)
    })


    it('shows the failure, not a crash, when every GET answers 500 { error }', async () => {
      await renderFailing(route.path, () => HttpResponse.json(apiError(MESSAGE), { status: 500 }))
      await expectFailureShown(route, MESSAGE)
      expectNoCrash()
      expectChrome()
    })


    it('survives every GET answering a JSON string', async () => {
      await renderFailing(route.path, () => HttpResponse.json('unexpected answer'))
      await settle(100)
      await landsOn(route.lands ?? route.path)
      expectNoCrash()
      expectChrome()
    })


    it('shows the failure, not a crash, when every GET drops the connection', async () => {
      await renderFailing(route.path, () => HttpResponse.error())
      await expectFailureShown(route, NETWORK_ERROR)
      expectNoCrash()
      expectChrome()
    })
  })
})
