// -----------------------------------------------------------
//  [*] Tests — the test harness itself (smoke)
//
//  Proves the foundation before anything is built on it: a
//  page's relative fetch requests reach the msw double and its
//  answers reach the screen, a backend refusal becomes the
//  page's own error presentation, the real App boots at a
//  route through its BrowserRouter, and the guards work — a
//  request the double does not know fails the test, and so
//  does a React bug report on the console.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, waitFor } from '@testing-library/react'
import { renderPage, renderApp } from '../support/render'
import { given } from '../support/backend/server'
import { allowUnhandledRequests, allowConsoleErrors } from '../support/setup'
import { expectNoCrash } from '../support/backend/contract'
import { wholeText } from '../support/regions'
import * as f from '../support/backend/fixtures'
import Reserves from '@/pages/Reserves/Reserves.jsx'


const renderReserves = () => renderPage(<Reserves />, { route: '/reserves' })







// -----------------------------------------------------------
// harness smoke
// -----------------------------------------------------------
//
// Uses the Reserves page — one request (the reserve wallets)
// and a plain error banner.
// -----------------------------------------------------------

describe('harness smoke', () => {

  it('renders a page whose request reaches the backend double', async () => {
    renderReserves()

    expect(await screen.findByText(f.RESERVE_LTC)).toBeInTheDocument()
    expect(screen.getByText('Litecoin Testnet4')).toBeInTheDocument()
    expectNoCrash()
  })


  it('shows the page\'s own error banner when the backend refuses', async () => {
    given.error('get', '/api/exchange/reserves', 'Internal server error', 500)
    renderReserves()

    expect(await screen.findByText('Internal server error')).toBeInTheDocument()
  })


  it('boots the real App at a route', async () => {
    renderApp({ route: '/reserves' })

    expect(await screen.findByText(f.RESERVE_KNF)).toBeInTheDocument()
    expect(window.location.pathname).toBe('/reserves')
  })


  it('sends an unknown path home', async () => {
    renderApp({ route: '/no/such/page' })

    await waitFor(() => expect(window.location.pathname).toBe('/'))
    expect(await screen.findByRole('heading', { level: 1, name: wholeText('Learn crypto by actually trading it') })).toBeInTheDocument()
  })


  it('records a request no handler answers (the test declares it expects one)', async () => {
    allowUnhandledRequests()
    await expect(fetch('/api/no-such-endpoint')).rejects.toThrow()
  })


  it('lets a test declare a console error it provokes on purpose', () => {
    allowConsoleErrors(/unique "key" prop/)
    console.error('Each child in a list should have a unique "key" prop.')
  })
})
