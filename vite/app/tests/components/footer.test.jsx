// -----------------------------------------------------------
//  [*] Tests — Footer (the note at the bottom of every page)
//
//  The copyright line, dated with the current year, and the
//  reminder that everything traded here is a valueless
//  testnet coin: on its own, the page's contentinfo landmark
//  with nothing to click in it; inside the App, the last thing
//  on every page, after the page itself. (The route sweep
//  checks it survives every backend failure of every route.)
// -----------------------------------------------------------

import { describe, it, expect, vi } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderPage, renderApp } from '../support/render'
import * as f from '../support/backend/fixtures'
import Footer from '@/pages/Exchange/components/Footer.jsx'


const copyright = (year) => `© ${year} VU KNF Coin Exchange — Vilnius university Kaunas faculty`
const REMINDER = 'Testnet coins only — KNF Coin and Litecoin Testnet4 have no real-world value.'

// What the footer reads, line by line
const lines = (footer) => Array.from(footer.children, (line) => line.textContent)

// DOM order is reading order: a before b
const precedes = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)

const renderFooterOn = (moment) => {
  vi.useFakeTimers({ toFake: ['Date'] })
  vi.setSystemTime(moment)
  return renderPage(<Footer />)
}







// -----------------------------------------------------------
// On its own
// -----------------------------------------------------------
//
// The footer rendered alone: the copyright line dated with
// the current year, the testnet reminder, and nothing to
// click.
// -----------------------------------------------------------

describe('Footer', () => {

  it('is the contentinfo landmark carrying the copyright line, dated this year', () => {
    renderFooterOn(f.NOW)
    expect(lines(screen.getByRole('contentinfo'))[0]).toBe(copyright(2026))
  })


  it('moves with the calendar — the year is always the current one', () => {
    renderFooterOn(new Date('2031-06-15T12:00:00Z'))
    expect(lines(screen.getByRole('contentinfo'))[0]).toBe(copyright(2031))
  })


  it('reminds the student that everything traded here is a valueless testnet coin', () => {
    renderFooterOn(f.NOW)
    expect(lines(screen.getByRole('contentinfo'))).toEqual([copyright(2026), REMINDER])
  })


  it('has nothing to click', () => {
    renderFooterOn(f.NOW)
    const footer = screen.getByRole('contentinfo')
    expect(within(footer).queryAllByRole('link')).toEqual([])
    expect(within(footer).queryAllByRole('button')).toEqual([])
  })
})







// -----------------------------------------------------------
// In the App shell
// -----------------------------------------------------------
//
// Inside the App the footer closes every page — once, after
// the page itself.
// -----------------------------------------------------------

describe('Footer in the App shell', () => {

  it.each(['/', '/exchange', '/reserves'])('closes %s: one footer, after the page', async (route) => {
    renderApp({ route })
    const footer = await screen.findByRole('contentinfo')
    expect(lines(footer)).toEqual([expect.stringMatching(/^© \d{4} VU KNF Coin Exchange — Vilnius university Kaunas faculty$/), REMINDER])
    expect(screen.getAllByRole('contentinfo')).toHaveLength(1)
    expect(precedes(screen.getByRole('main'), footer)).toBe(true)
  })
})
