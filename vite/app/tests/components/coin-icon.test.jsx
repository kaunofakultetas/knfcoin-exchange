// -----------------------------------------------------------
//  [*] Tests — CoinIcon (the mark of a coin)
//
//  The mark on its own: the logo the backend advertises, as a
//  decorative image of the asked size; without one — or once
//  it failed to load — a round dot whose colour comes from the
//  coin's label alone (the same for the same coin everywhere,
//  the two coins told apart, a vivid tone, a neutral grey with
//  no label at all); a new logo URL tried afresh while a
//  failed one stays the dot; never squeezed by the row it sits
//  in. Then the promise of the header on a real page: the swap
//  panels and the order list show the same mark for the same
//  coin, as logos and, when the logo file is missing, as dots.
//
//  The dot has no accessible handle — its computed style is
//  the witness (jsdom resolves the HSL to rgb).
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { useState } from 'react'
import { act, fireEvent, screen, within } from '@testing-library/react'
import { renderPage } from '../support/render'
import { RATE_LINE, orderRows, panel, recentOrders, renderExchange } from '../support/exchange/page'
import * as f from '../support/backend/fixtures'
import CoinIcon from '@/pages/Exchange/components/CoinIcon.jsx'


// The mark rendered into a slot of its own render, so the test
// can hold the element whatever it turned out to be (a logo or
// a dot) — several renders may share one test. New props reach
// the SAME instance through the host's state (a bare rerender
// would drop renderPage's frame and remount the mark, hiding
// what it remembers)
function MarkHost({ initial, control }) {
  const [props, setProps] = useState(initial)
  control.setProps = setProps
  return <div data-testid="slot"><CoinIcon {...props} /></div>
}

const renderMark = (props) => {
  const control = {}
  const view = renderPage(<MarkHost initial={props} control={control} />)
  const mark = () => within(view.container).getByTestId('slot').firstElementChild
  const rerender = (next) => act(() => control.setProps(next))
  return { mark, rerender }
}

const colourOf = (element) => getComputedStyle(element).backgroundColor

// A dot's colour — its hue at 65 % saturation and 55 %
// lightness — in rgb: the strongest channel is always 215 and
// the weakest 66, whatever the hue
const channels = (rgb) => rgb.match(/\d+/g).map(Number)

// The coin mark inside a part of the page: its logo, or its dot
const markIn = (element) => element.querySelector('img, span[style*="background-color"]')







// -----------------------------------------------------------
// The logo
// -----------------------------------------------------------
//
// A coin whose answer advertised a logo shows it — until the
// image fails to load, which leaves the coin's dot instead.
// -----------------------------------------------------------

describe('CoinIcon with a logo', () => {

  it('shows the advertised logo as a decorative image of the asked size', () => {
    const { mark } = renderMark({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf', size: 24 })
    const logo = mark()
    expect(logo.tagName).toBe('IMG')
    expect(logo).toHaveAttribute('src', '/api/exchange/icons/knf')
    expect(logo).toHaveAttribute('alt', '')
    expect(getComputedStyle(logo).width).toBe('24px')
    expect(getComputedStyle(logo).height).toBe('24px')
  })


  it('is 28 pixels when no size is asked', () => {
    const { mark } = renderMark({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf' })
    expect(getComputedStyle(mark()).width).toBe('28px')
    expect(getComputedStyle(mark()).height).toBe('28px')
  })


  it('falls back to the coin\'s dot when the logo fails to load', () => {
    const { mark } = renderMark({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf', size: 24 })
    const dotColour = colourOf(renderMark({ asset: 'KNF Coin', size: 24 }).mark())

    fireEvent.error(mark())

    expect(mark().tagName).toBe('SPAN')
    expect(colourOf(mark())).toBe(dotColour)
    expect(getComputedStyle(mark()).width).toBe('24px')
  })


  it('stays the dot while the failed logo stays the same', () => {
    const { mark, rerender } = renderMark({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf', size: 24 })
    fireEvent.error(mark())

    rerender({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf', size: 40 })

    expect(mark().tagName).toBe('SPAN')
    expect(getComputedStyle(mark()).width).toBe('40px')
  })


  it('tries a new logo afresh — one failed logo never blanks the next coin', () => {
    const { mark, rerender } = renderMark({ asset: 'KNF Coin', icon: '/api/exchange/icons/knf', size: 24 })
    fireEvent.error(mark())
    expect(mark().tagName).toBe('SPAN')

    // A swap panel keeps its instance when the direction flips
    rerender({ asset: 'LTC Testnet', icon: '/api/exchange/icons/ltc4', size: 24 })

    expect(mark().tagName).toBe('IMG')
    expect(mark()).toHaveAttribute('src', '/api/exchange/icons/ltc4')
  })
})







// -----------------------------------------------------------
// The dot
// -----------------------------------------------------------
//
// A coin without a logo: a round dot in a colour that belongs
// to the coin's label.
// -----------------------------------------------------------

describe('CoinIcon without a logo', () => {

  it('is a round dot of the asked size', () => {
    const { mark } = renderMark({ asset: 'LTC Testnet', size: 24 })
    expect(mark().tagName).toBe('SPAN')
    expect(mark()).toHaveClass('rounded-full')
    expect(getComputedStyle(mark()).width).toBe('24px')
    expect(getComputedStyle(mark()).height).toBe('24px')
  })


  it.each([null, undefined, ''])('a logo of %j is the dot too', (icon) => {
    expect(renderMark({ asset: 'LTC Testnet', icon }).mark().tagName).toBe('SPAN')
  })


  it('colours the same coin the same, in every instance', () => {
    const first = colourOf(renderMark({ asset: 'KNF Coin', size: 24 }).mark())
    const second = colourOf(renderMark({ asset: 'KNF Coin', size: 40 }).mark())
    expect(first).toBe(second)
  })


  it('tells the two coins apart by colour', () => {
    const colours = [f.KNF, f.LTC].map((asset) => colourOf(renderMark({ asset }).mark()))
    expect(new Set(colours).size).toBe(2)
  })


  it('is always a vivid mid tone — only the hue follows the label', () => {
    for (const asset of [f.KNF, f.LTC, 'x', 'Ąžuolas 💾', 'k'.repeat(5000)]) {
      const rgb = channels(colourOf(renderMark({ asset }).mark()))
      expect(Math.max(...rgb), asset).toBe(215)
      expect(Math.min(...rgb), asset).toBe(66)
    }
  })


  it('is a neutral grey with no label to colour it by', () => {
    expect(colourOf(renderMark({}).mark())).toBe('rgb(158, 158, 158)')
    expect(colourOf(renderMark({ asset: '' }).mark())).toBe('rgb(158, 158, 158)')
  })
})







// -----------------------------------------------------------
// Placement
// -----------------------------------------------------------
//
// Beside the coin's name in a flex row the mark keeps its
// size, logo and dot alike.
// -----------------------------------------------------------

describe('CoinIcon placement', () => {

  it.each([
    ['the logo', { icon: '/api/exchange/icons/knf' }],
    ['the dot', {}],
  ])('%s never shrinks beside the coin\'s name', (_, props) => {
    expect(renderMark({ asset: 'KNF Coin', size: 30, ...props }).mark()).toHaveClass('flex-none')
  })
})







// -----------------------------------------------------------
// One mark per coin, everywhere
// -----------------------------------------------------------
//
// The exchange page draws coins from two answers — the swap
// panels from the rates, the list from each order — and both
// must show the same coin the same way.
// -----------------------------------------------------------

describe('CoinIcon across the exchange page', () => {

  const marksOfKnf = async () => {
    renderExchange()
    await screen.findByText(RATE_LINE)
    await within(recentOrders()).findAllByRole('link')
    // The awaiting order is KNF Coin → LTC Testnet, its first coin KNF
    return { inPanel: () => markIn(panel('You send')), inList: () => markIn(orderRows()[0]) }
  }


  it('the swap panel and the order list show the same logo for the same coin', async () => {
    const { inPanel, inList } = await marksOfKnf()
    expect(inPanel()).toHaveAttribute('src', f.ICONS[f.KNF])
    expect(inList()).toHaveAttribute('src', f.ICONS[f.KNF])
  })


  it('with the logo file missing, both fall back to the same dot', async () => {
    const { inPanel, inList } = await marksOfKnf()

    fireEvent.error(inPanel())
    fireEvent.error(inList())

    expect(inPanel().tagName).toBe('SPAN')
    expect(inList().tagName).toBe('SPAN')
    expect(colourOf(inPanel())).toBe(colourOf(inList()))
  })
})
