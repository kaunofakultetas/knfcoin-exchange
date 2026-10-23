// -----------------------------------------------------------
//  [*] Tests — Header (the brand and the navigation pills)
//
//  The page's banner: the brand — the KNF Coin logo the app
//  ships with, beside its name — leading home, then the four
//  pills — Home, Exchange and Reserves followed by the router
//  inside the app, Explorer a plain link the browser follows
//  to the block explorer Caddy serves outside it. The pill of
//  the page the student is on is highlighted (the ring that
//  sets it apart is the only sign of it, so that is what the
//  tests read), and only that one — on an order's page, a
//  step of the Exchange tool, the Exchange pill.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderPage } from '../support/render'
import { LocationProbe, currentPath, followedByTheBrowser } from '../support/shell/router'
import * as f from '../support/backend/fixtures'
import Header from '@/pages/Exchange/components/Header.jsx'


const renderHeader = (path) => renderPage(<><Header currentPath={path} /><LocationProbe /></>, { route: path })

const nav = () => screen.getByRole('navigation')
const pills = () => within(nav()).getAllByRole('link')
const pill = (name) => within(nav()).getByRole('link', { name })
const brand = () => within(screen.getByRole('banner')).getByRole('link', { name: /KNF Exchange$/ })

// The pills that wear the highlight ring, by name
const highlighted = () => pills().filter((link) => link.classList.contains('ring-1')).map((link) => link.textContent)

// DOM order is reading order: a before b
const precedes = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)







// -----------------------------------------------------------
// The brand and the pills
// -----------------------------------------------------------
//
// What the banner holds and where each link leads: the brand
// home, three pills inside the app, the Explorer pill left to
// the browser.
// -----------------------------------------------------------

describe('Header', () => {

  it('is the page\'s banner: the brand first, then the navigation', () => {
    renderHeader('/')
    const banner = screen.getByRole('banner')
    expect(within(banner).getByRole('navigation')).toBe(nav())
    expect(precedes(brand(), nav())).toBe(true)
  })


  it('offers Home, Exchange, Reserves and Explorer, in that order', () => {
    renderHeader('/')
    expect(pills().map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
      ['Home', '/'],
      ['Exchange', '/exchange'],
      ['Reserves', '/reserves'],
      ['Explorer', '/explorer/'],
    ])
  })


  it('the brand wears the KNF Coin logo the app ships with — decorative, its words name the link', () => {
    renderHeader('/')
    const logo = brand().querySelector('img')
    expect(logo).toHaveAttribute('src', '/img/logo_knfcoin.svg')
    expect(logo).toHaveAttribute('alt', '')
    expect(brand()).toHaveAccessibleName('KNF Exchange')
  })


  it('the brand leads home inside the app', async () => {
    const { user } = renderHeader('/reserves')
    expect(brand()).toHaveAttribute('href', '/')
    await user.click(brand())
    expect(currentPath()).toBe('/')
  })


  it.each([
    ['Home', '/reserves', '/'],
    ['Exchange', '/', '/exchange'],
    ['Reserves', '/', '/reserves'],
  ])('"%s" is followed by the router', async (name, from, to) => {
    const { user } = renderHeader(from)
    await user.click(pill(name))
    expect(currentPath()).toBe(to)
  })


  it('"Explorer" is a plain link, left to the browser — the explorer lives outside the app', () => {
    renderHeader('/')
    expect(followedByTheBrowser(pill('Explorer'))).toBe(true)
    expect(currentPath()).toBe('/')
  })
})







// -----------------------------------------------------------
// Where the student is
// -----------------------------------------------------------
//
// Which pill wears the highlight ring for the path the
// student is on — a tool's own page and every page under it.
// -----------------------------------------------------------

describe('Header — where the student is', () => {

  it.each([
    ['/', 'Home'],
    ['/exchange', 'Exchange'],
    ['/reserves', 'Reserves'],
  ])('on %s only "%s" is highlighted', (path, name) => {
    renderHeader(path)
    expect(highlighted()).toEqual([name])
  })


  it('on a path no pill names, none is', () => {
    renderHeader('/nieko')
    expect(highlighted()).toEqual([])
  })


  it('on an order\'s page the Exchange pill stays highlighted', () => {
    renderHeader(`/exchange/order/${f.COMPLETED_ID}`)
    expect(highlighted()).toEqual(['Exchange'])
  })


  it('a path that only begins like a tool\'s highlights nothing', () => {
    renderHeader('/exchanges')
    expect(highlighted()).toEqual([])
  })
})
