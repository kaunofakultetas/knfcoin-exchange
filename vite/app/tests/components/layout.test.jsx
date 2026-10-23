// -----------------------------------------------------------
//  [*] Tests — Layout (the shell every page renders inside)
//
//  The page between the header and the footer, as the one main
//  landmark; the header told where the student is — on arrival
//  and after every move — so its highlight follows the
//  location; and the backdrop behind it all, which is
//  decoration: hidden from assistive technology, without a
//  word in it.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { screen, within } from '@testing-library/react'
import { renderPage } from '../support/render'
import Layout from '@/pages/Exchange/components/Layout.jsx'


const renderLayout = (route = '/') => renderPage(<Layout><p>The page itself</p></Layout>, { route })

// The pills that wear the highlight ring, by name
const highlighted = () => within(screen.getByRole('navigation')).getAllByRole('link')
  .filter((link) => link.classList.contains('ring-1')).map((link) => link.textContent)

// DOM order is reading order: a before b
const precedes = (a, b) => Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING)







// -----------------------------------------------------------
// The frame
// -----------------------------------------------------------
//
// The shell every page renders in: the header, the page as
// the one main landmark and the footer, the current path told
// to the header, the backdrop kept out of assistive
// technology.
// -----------------------------------------------------------

describe('Layout', () => {

  it('puts the page between the header and the footer, as the one main landmark', () => {
    renderLayout()
    const main = screen.getByRole('main')
    expect(within(main).getByText('The page itself')).toBeInTheDocument()
    expect(precedes(screen.getByRole('banner'), main)).toBe(true)
    expect(precedes(main, screen.getByRole('contentinfo'))).toBe(true)
    expect(screen.getAllByRole('main')).toHaveLength(1)
  })


  it('tells the header where the student is', () => {
    renderLayout('/reserves')
    expect(highlighted()).toEqual(['Reserves'])
  })


  it('keeps telling it as the student moves on', async () => {
    const { user } = renderLayout('/reserves')
    await user.click(within(screen.getByRole('navigation')).getByRole('link', { name: 'Exchange' }))
    expect(highlighted()).toEqual(['Exchange'])
  })


  it('the backdrop is decoration: hidden from assistive technology, without a word in it', () => {
    const { container } = renderLayout()
    const hidden = container.querySelectorAll('[aria-hidden="true"]')
    expect(hidden).toHaveLength(1)
    expect(hidden[0].textContent).toBe('')
    expect(hidden[0].contains(screen.getByRole('main'))).toBe(false)
  })
})
