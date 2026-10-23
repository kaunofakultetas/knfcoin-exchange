// -----------------------------------------------------------
//  [*] Tests — Home page (/)
//
//  The hub students land on: the hero — the badge, the
//  headline, what the playground is for and "Start swapping" —
//  with the live KNF → tLTC4 rate beside it, the two tool
//  cards (the exchange inside the app, the block explorer the
//  browser opens from Caddy) and the three steps of a swap.
//  The rate comes from one request, made once — the home page
//  does not poll — and shows nothing at all until it answers,
//  and nothing when it fails. The backend contract of GET
//  /api/exchange/rates as this page consumes it closes the
//  file.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderPage } from '../support/render'
import { given } from '../support/backend/server'
import { describeEndpointContract, settle } from '../support/backend/contract'
import { LocationProbe, currentPath, followedByTheBrowser } from '../support/shell/router'
import { watchRequests } from '../support/shell/requests'
import { wholeText } from '../support/regions'
import * as f from '../support/backend/fixtures'
import Home from '@/pages/Home/Home.jsx'


const HEADLINE = 'Learn crypto by actually trading it'
const RATE_LINE = '1 KNF ≈ 0.12345678 tLTC4'

const renderHome = () => renderPage(<><Home /><LocationProbe /></>, { route: '/' })

const main = () => screen.getByRole('main')
const headline = () => within(main()).getByRole('heading', { level: 1, name: wholeText(HEADLINE) })

// A tool card is one link holding the tool's name and what it
// does
const card = (title) => within(main()).getByRole('link', { name: new RegExp(`^\\S+ ${title}→`) })

// The live rate chip, when it shows
const rateChip = () => within(main()).queryByText(/^1 KNF ≈ .* tLTC4$/)







// -----------------------------------------------------------
// The hero
// -----------------------------------------------------------
//
// What the playground is, and the button into the exchange.
// -----------------------------------------------------------

describe('Home — the hero', () => {

  it('introduces the playground: the badge, the headline and what it is for', () => {
    renderHome()
    expect(within(main()).getByText('Testnet playground')).toBeInTheDocument()
    expect(headline()).toBeInTheDocument()
    expect(within(main()).getByText('A safe sandbox for VU Kaunas faculty students to learn how a cryptocurrency exchange works — swap KNF Coin and Litecoin Testnet4 and watch every order settle on-chain.')).toBeInTheDocument()
  })


  it('"Start swapping" opens the exchange inside the app', async () => {
    const { user } = renderHome()
    await user.click(within(main()).getByRole('link', { name: 'Start swapping' }))
    expect(currentPath()).toBe('/exchange')
  })
})







// -----------------------------------------------------------
// The live rate
// -----------------------------------------------------------
//
// The KNF → tLTC4 rate under the hero: read once, rounded to
// eight decimals, nothing shown until it is there.
// -----------------------------------------------------------

describe('Home — the live rate', () => {

  it('shows the KNF → tLTC4 rate once the backend answers', async () => {
    renderHome()
    expect(await within(main()).findByText(RATE_LINE)).toBeInTheDocument()
  })


  it('rounds the rate to eight decimals', async () => {
    given.json('get', '/api/exchange/rates', { ...f.rates, pairs: { ...f.rates.pairs, 'KNF Coin->LTC Testnet': 0.123456789123 } })
    renderHome()
    expect(await within(main()).findByText('1 KNF ≈ 0.12345679 tLTC4')).toBeInTheDocument()
  })


  it('shows nothing until then — no placeholder', async () => {
    given.hang('get', '/api/exchange/rates')
    renderHome()
    await settle(100)
    expect(rateChip()).toBeNull()
    expect(headline()).toBeInTheDocument()
  })


  it('shows nothing when the rates cannot be read — the page stands as it is', async () => {
    given.error('get', '/api/exchange/rates', 'Internal server error', 500)
    renderHome()
    await settle(100)
    expect(rateChip()).toBeNull()
    expect(within(main()).queryByText('Internal server error')).toBeNull()
    expect(headline()).toBeInTheDocument()
  })


  it('shows nothing when the answer has no KNF → tLTC4 pair', async () => {
    given.json('get', '/api/exchange/rates', { ...f.rates, pairs: { 'LTC Testnet->KNF Coin': f.RATE_LTC_KNF } })
    renderHome()
    await settle(100)
    expect(rateChip()).toBeNull()
  })


  it('asks for the rates once, and nothing else — the home page does not poll', async () => {
    const seen = watchRequests()
    renderHome()
    await within(main()).findByText(RATE_LINE)
    await settle(100)
    expect(seen).toEqual(['GET /api/exchange/rates'])
  })
})







// -----------------------------------------------------------
// The tools
// -----------------------------------------------------------
//
// The two tool cards: the exchange inside the app, the block
// explorer a plain link the browser follows.
// -----------------------------------------------------------

describe('Home — the tools', () => {

  it('offers the exchange, saying what it does, as a link inside the app', async () => {
    const { user } = renderHome()
    const exchange = card('Exchange')
    expect(exchange).toHaveTextContent('Swap KNF Coin and Litecoin Testnet4, then follow your order from deposit to payout.')
    expect(exchange).toHaveAttribute('href', '/exchange')

    await user.click(exchange)
    expect(currentPath()).toBe('/exchange')
  })


  it('offers the block explorer, saying what it shows, as a plain link the browser follows to Caddy', () => {
    renderHome()
    const explorer = card('Block Explorer')
    expect(explorer).toHaveTextContent('Browse KNF Coin blocks, transactions and addresses in real time — including your own swaps.')
    expect(explorer).toHaveAttribute('href', '/explorer/')
    expect(followedByTheBrowser(explorer)).toBe(true)
    expect(currentPath()).toBe('/')
  })
})







// -----------------------------------------------------------
// How a swap works
// -----------------------------------------------------------
//
// The three numbered steps that explain a swap.
// -----------------------------------------------------------

describe('Home — how a swap works', () => {

  it('explains a swap in three numbered steps', () => {
    renderHome()
    const section = within(main()).getByRole('heading', { level: 2, name: 'How a swap works' }).closest('section')
    const steps = ['Create an order', 'Send your deposit', 'Receive on-chain'].map((title) => within(section).getByText(title).parentElement.parentElement)

    expect(steps.map((step) => step.firstElementChild.textContent)).toEqual(['1', '2', '3'])
    expect(steps[0]).toHaveTextContent('Pick a direction and amount, and tell us the address you want to receive on.')
    expect(steps[1]).toHaveTextContent('Pay the unique deposit address (or scan its QR code) before the order expires.')
    expect(steps[2]).toHaveTextContent('Once your deposit confirms, the exchange pays out to your address automatically — or, if it cannot, sends your coins back.')
  })
})







// -----------------------------------------------------------
// Backend contract — GET /api/exchange/rates on the home page
// -----------------------------------------------------------
//
// Loaded: the rate chip. A failure: no chip, and no word of
// it — the hero stands as it is. In flight: no chip either.
// Whatever the body: no crash, the headline stands.
// -----------------------------------------------------------

describeEndpointContract({
  path: '/api/exchange/rates',
  fixture: f.rates,
  render: () => renderHome(),
  chrome: () => headline(),
  loaded: async () => {
    expect(await within(main()).findByText(RATE_LINE)).toBeInTheDocument()
  },
  failed: async () => {
    await settle(50)
    expect(rateChip()).toBeNull()
  },
  loading: () => rateChip() === null,
})
