// -----------------------------------------------------------
//  [*] Tests — Reserves page (/reserves)
//
//  The operator's view of the payout wallets: the title and
//  how often the balances refresh, the loading state, then a
//  card per chain in the backend's order — the chain's logo,
//  name and ticker, the confirmed balance, the coins pending
//  (arriving or leaving), what it can still pay out to new
//  orders and the warning when that is nothing — the exchange
//  then refuses the orders it would pay out — the reason when
//  a balance could not be read (the address still
//  shown, so the wallet can be topped up anyway), the top-up
//  address to copy and the chain's explorer in a new tab. The
//  page refreshes every 10 seconds: a failed refresh keeps the
//  cards under an error banner — the words that came back, the
//  page's own sentence when none came — which goes when a
//  refresh gets through, and nothing is asked once the
//  operator has left.
//  The backend contract of GET /api/exchange/reserves closes
//  the file.
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { act, screen, within } from '@testing-library/react'
import { renderPage } from '../support/render'
import { given } from '../support/backend/server'
import { describeEndpointContract, settle } from '../support/backend/contract'
import { watchRequests } from '../support/shell/requests'
import { regionHolding } from '../support/regions'
import * as f from '../support/backend/fixtures'
import { ExchangeApi } from '@/pages/Exchange/lib/api.js'
import Reserves from '@/pages/Reserves/Reserves.jsx'


const renderReserves = () => renderPage(<Reserves />, { route: '/reserves' })

const main = () => screen.getByRole('main')
const pageHeading = () => within(main()).getByRole('heading', { level: 1, name: 'Exchange reserves' })

// The page with its cards in
const renderLoaded = async () => {
  const view = renderReserves()
  await within(main()).findByText('Litecoin Testnet4')
  return view
}

// A chain's card: the smallest part of the page holding its
// name and the top-up label every card carries
const card = (name) => regionHolding(name, 'Top-up address:')

// The coin logo a card shows, by the URL it was drawn from
const logoOf = (element) => element.querySelector('img')?.getAttribute('src') ?? null

// The reserves answering with these entries
const reservesOf = (...entries) => given.json('get', '/api/exchange/reserves', entries)
const knf = (changes = {}) => ({ ...f.reserves()[0], ...changes })
const ltc = (changes = {}) => ({ ...f.reserves()[1], ...changes })

const refresh = async (times = 1) => {
  await act(async () => { vi.advanceTimersByTime(10000 * times) })
  await settle(50)
}







// -----------------------------------------------------------
// The page
// -----------------------------------------------------------
//
// The title and the refresh rate, the loading state, and the
// one read the page makes.
// -----------------------------------------------------------

describe('Reserves — the page', () => {

  it('titles the page and says how often the balances refresh', async () => {
    renderReserves()
    expect(pageHeading()).toBeInTheDocument()
    expect(within(main()).getByText('Payouts are funded from these wallets — top up whichever runs low. Balances refresh every 10 seconds.')).toBeInTheDocument()
    await within(main()).findByText('Litecoin Testnet4')
  })


  it('says it is loading until the reserves arrive', async () => {
    given.hang('get', '/api/exchange/reserves')
    renderReserves()
    await settle(100)
    expect(within(main()).getByText('Loading reserves...')).toBeInTheDocument()
  })


  it('asks for the reserves, and nothing else', async () => {
    const seen = watchRequests()
    await renderLoaded()
    await settle(100)
    expect(seen).toEqual(['GET /api/exchange/reserves'])
  })
})







// -----------------------------------------------------------
// A card per chain
// -----------------------------------------------------------
//
// One card per chain: its balance, coins pending either way,
// the empty-reserve warning, the reason a balance is missing,
// the top-up address and the explorer link.
// -----------------------------------------------------------

describe('Reserves — a card per chain', () => {

  it('shows one card per chain, in the backend\'s order, each named with its ticker', async () => {
    await renderLoaded()
    const names = within(main()).getAllByText(/^Reserve wallet · /).map((line) => [line.previousElementSibling.textContent, line.textContent])
    expect(names).toEqual([
      ['KNF Coin', 'Reserve wallet · KNF'],
      ['Litecoin Testnet4', 'Reserve wallet · tLTC4'],
    ])
    expect(logoOf(card('KNF Coin'))).toBe('/api/exchange/icons/knf')
    expect(logoOf(card('Litecoin Testnet4'))).toBe('/api/exchange/icons/ltc4')
  })


  it('shows the confirmed balance, thousands grouped, with the ticker', async () => {
    await renderLoaded()
    expect(within(card('KNF Coin')).getByText('4,821.5')).toHaveTextContent(/^4,821\.5KNF$/)
    expect(within(card('Litecoin Testnet4')).getByText('0.00104235')).toHaveTextContent(/^0\.00104235tLTC4$/)
  })


  it('shows the coins on their way as pending, and no such line when nothing is pending', async () => {
    await renderLoaded()
    expect(within(card('Litecoin Testnet4')).getByText('140 tLTC4 pending confirmation')).toBeInTheDocument()
    expect(within(card('KNF Coin')).queryByText(/pending confirmation$/)).toBeNull()
  })


  it('says what each reserve can still pay out to new orders', async () => {
    await renderLoaded()
    expect(within(card('KNF Coin')).getByText('4,817.44997147 KNF available for new orders')).toBeInTheDocument()
    expect(within(card('Litecoin Testnet4')).getByText('135.3713708 tLTC4 available for new orders')).toBeInTheDocument()
  })


  it('coins leaving the reserve are pending too, as a negative amount', async () => {
    reservesOf(knf({ unconfirmed: -0.5 }))
    renderReserves()
    expect(await within(main()).findByText('-0.5 KNF pending confirmation')).toBeInTheDocument()
  })


  it('warns about an empty reserve — the orders it would pay out are refused', async () => {
    reservesOf(knf(), ltc({ confirmed: 0, unconfirmed: 0, available: 0 }))
    await renderLoaded()
    expect(within(card('Litecoin Testnet4')).getByText('Nothing to spare — orders paying out on this chain are refused until it is topped up.')).toBeInTheDocument()
    expect(within(card('KNF Coin')).queryByText(/^Nothing to spare —/)).toBeNull()
  })


  it('a reserve owed all it holds has nothing to spare either', async () => {
    reservesOf(ltc({ confirmed: 1.5, unconfirmed: 0, available: 0 }))
    await renderLoaded()
    expect(within(card('Litecoin Testnet4')).getByText('0 tLTC4 available for new orders')).toBeInTheDocument()
    expect(within(card('Litecoin Testnet4')).getByText(/^Nothing to spare —/)).toBeInTheDocument()
  })


  it('a reserve whose coins are still confirming can pay out what they bring', async () => {
    // A payout spends unconfirmed coins once the confirmed ones fall short
    reservesOf(ltc({ confirmed: 0, unconfirmed: 40, available: 39.9999859 }))
    await renderLoaded()
    expect(within(card('Litecoin Testnet4')).getByText('40 tLTC4 pending confirmation')).toBeInTheDocument()
    expect(within(card('Litecoin Testnet4')).getByText('39.9999859 tLTC4 available for new orders')).toBeInTheDocument()
    expect(within(card('Litecoin Testnet4')).queryByText(/^Nothing to spare —/)).toBeNull()
  })


  it('an answer without what is available warns on an empty confirmed balance alone', async () => {
    reservesOf(ltc({ confirmed: 0, unconfirmed: 40, available: undefined }))
    await renderLoaded()
    expect(within(card('Litecoin Testnet4')).queryByText(/available for new orders$/)).toBeNull()
    expect(within(card('Litecoin Testnet4')).getByText(/^Nothing to spare —/)).toBeInTheDocument()
  })


  it.each([
    ['still syncing', f.RESERVE_SYNCING],
    ['unreachable', f.RESERVE_UNREACHABLE],
  ])('a chain whose Electrum server is %s says why — and still offers its address', async (_, reason) => {
    reservesOf(knf(), ltc({ confirmed: null, unconfirmed: null, available: null, error: reason }))
    await renderLoaded()
    const ltcCard = card('Litecoin Testnet4')
    expect(within(ltcCard).getByText(`Balance unavailable: ${reason}`)).toBeInTheDocument()
    expect(within(ltcCard).getByText(f.RESERVE_LTC)).toBeInTheDocument()
    expect(within(ltcCard).queryByText(/pending confirmation$|available for new orders$|^Nothing to spare —/)).toBeNull()
    expect(within(card('KNF Coin')).getByText('4,821.5')).toBeInTheDocument()
  })


  it('offers the top-up address with a button that copies it', async () => {
    const { user } = await renderLoaded()
    const write = vi.spyOn(navigator.clipboard, 'writeText')
    const ltcCard = card('Litecoin Testnet4')

    expect(within(ltcCard).getByText(f.RESERVE_LTC)).toBeInTheDocument()
    await user.click(within(ltcCard).getByRole('button', { name: 'Copy' }))

    expect(write).toHaveBeenCalledExactlyOnceWith(f.RESERVE_LTC)
  })


  it('links to the chain\'s explorer in a new tab, without handing it this page', async () => {
    await renderLoaded()
    const link = within(card('Litecoin Testnet4')).getByRole('link', { name: 'View on block explorer →' })
    expect(link).toHaveAttribute('href', 'https://litecoinspace.org/testnet')
    expect(link).toHaveAttribute('target', '_blank')
    expect(link).toHaveAttribute('rel', 'noreferrer')
    expect(within(card('KNF Coin')).getByRole('link', { name: 'View on block explorer →' })).toHaveAttribute('href', '/explorer')
  })


  it('without an explorer, offers no link', async () => {
    reservesOf(knf({ block_explorer: null }))
    renderReserves()
    await within(main()).findByText(f.RESERVE_KNF)
    expect(within(main()).queryByRole('link', { name: 'View on block explorer →' })).toBeNull()
  })
})







// -----------------------------------------------------------
// Refreshing
// -----------------------------------------------------------
//
// Only the intervals are faked: the answers still travel
// through msw on real timers.
// -----------------------------------------------------------

describe('Reserves — refreshing', () => {

  it('refreshes every 10 seconds — a new balance shows', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    given.sequence('get', '/api/exchange/reserves', [
      { body: f.reserves() },
      { body: [knf(), ltc({ confirmed: 40.00104235, unconfirmed: 0 })] },
    ])
    await renderLoaded()

    await refresh()

    expect(within(card('Litecoin Testnet4')).getByText('40.00104235')).toBeInTheDocument()
    expect(within(card('Litecoin Testnet4')).queryByText(/pending confirmation$/)).toBeNull()
  })


  it('a failed refresh keeps the cards, under a banner saying what went wrong', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    given.sequence('get', '/api/exchange/reserves', [
      { body: f.reserves() },
      { status: 500, body: { error: 'Internal server error' } },
    ])
    await renderLoaded()

    await refresh()

    expect(within(main()).getByText('Internal server error')).toBeInTheDocument()
    expect(within(card('KNF Coin')).getByText('4,821.5')).toBeInTheDocument()
  })


  it('the banner goes once a refresh gets through', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    given.sequence('get', '/api/exchange/reserves', [
      { body: f.reserves() },
      { error: true },
      { body: f.reserves() },
    ])
    await renderLoaded()
    await refresh()
    expect(within(main()).getByText('Failed to fetch')).toBeInTheDocument()

    await refresh()

    expect(within(main()).queryByText('Failed to fetch')).toBeNull()
  })


  it('a first read that fails shows the banner alone — no cards, no loading', async () => {
    given.error('get', '/api/exchange/reserves', 'Internal server error', 500)
    renderReserves()
    expect(await within(main()).findByText('Internal server error')).toBeInTheDocument()
    expect(within(main()).queryByText('Loading reserves...')).toBeNull()
    expect(within(main()).queryByText('Top-up address:')).toBeNull()
  })


  it('a failure that comes without words falls back to the page\'s own sentence', async () => {
    // No answer of the backend makes ExchangeApi fail without
    // naming a reason, so ExchangeApi itself fails silently here
    vi.spyOn(ExchangeApi, 'getReserves').mockRejectedValue(new Error(''))
    renderReserves()
    expect(await within(main()).findByText('Failed to load reserves')).toBeInTheDocument()
  })


  it('asks nothing more once the operator has left', async () => {
    vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
    const seen = watchRequests()
    const { unmount } = await renderLoaded()

    unmount()
    await refresh(5)

    expect(seen).toHaveLength(1)
  })
})







// -----------------------------------------------------------
// Backend contract — GET /api/exchange/reserves
// -----------------------------------------------------------
//
// Loaded: the cards. A failure: the error banner with the
// words that came back. In flight: "Loading reserves...".
// Whatever the body: no crash, the title stands — entries
// without their network included.
// -----------------------------------------------------------

describeEndpointContract({
  path: '/api/exchange/reserves',
  fixture: f.reserves(),
  render: () => renderReserves(),
  chrome: () => pageHeading(),
  loaded: async () => {
    expect(await within(main()).findByText('Litecoin Testnet4')).toBeInTheDocument()
  },
  failed: async (says) => {
    expect(await within(main()).findByText(says)).toBeInTheDocument()
  },
  loading: () => within(main()).queryByText('Loading reserves...'),
})
