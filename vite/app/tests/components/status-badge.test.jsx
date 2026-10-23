// -----------------------------------------------------------
//  [*] Tests — StatusBadge (an order's lifecycle pill)
//
//  The label of every status the backend writes, the pulsing
//  dot that marks the orders still moving (awaiting a deposit,
//  confirming, exchanging, sending, its coins on their way
//  back) and its absence on the finished ones — and the
//  fallback that keeps a status the frontend does not know yet
//  from breaking anything: it is shown as the backend wrote
//  it, without a dot.
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ORDER_STATUS } from '@/pages/Exchange/lib/orders.js'
import StatusBadge from '@/pages/Exchange/components/StatusBadge.jsx'


// Every status with the label the student reads
const LABELS = [
  ['awaiting_deposit', 'Awaiting deposit'],
  ['awaiting_confirmations', 'Confirming'],
  ['exchanging', 'Exchanging'],
  ['sending', 'Sending'],
  ['refunding', 'Refunding'],
  ['completed', 'Completed'],
  ['expired', 'Expired'],
  ['refunded', 'Refunded'],
  ['failed', 'Failed'],
  ['reversed', 'Reversed'],
]

const IN_FLIGHT = ['awaiting_deposit', 'awaiting_confirmations', 'exchanging', 'sending', 'refunding']
const FINISHED = ['completed', 'expired', 'refunded', 'failed', 'reversed']

// A status no backend writes yet
const UNKNOWN = 'cancelled'

// The badge as one element: its label, and the dot when the
// order is still moving (an empty span inside it)
const badgeOf = (status) => render(<StatusBadge status={status} />).container.firstElementChild
const hasDot = (badge) => badge.querySelector('span') !== null







// -----------------------------------------------------------
// Labels
// -----------------------------------------------------------
//
// The word each status reads as — the backend's own string
// for a status the badge does not know, an empty pill rather
// than a failure when there is none.
// -----------------------------------------------------------

describe('StatusBadge — labels', () => {

  it.each(LABELS)('%s reads "%s"', (status, label) => {
    expect(badgeOf(status)).toHaveTextContent(new RegExp(`^${label}$`))
  })


  it('names every status lib/orders.js lists — none falls back to the raw string', () => {
    for (const status of Object.values(ORDER_STATUS)) {
      expect(badgeOf(status).textContent, status).not.toBe(status)
    }
  })


  it('shows a status it does not know as the backend wrote it', () => {
    expect(badgeOf(UNKNOWN)).toHaveTextContent(/^cancelled$/)
  })


  it('a missing status leaves an empty pill rather than failing', () => {
    expect(badgeOf(undefined).textContent).toBe('')
  })
})







// -----------------------------------------------------------
// The pulsing dot
// -----------------------------------------------------------
//
// The dot that marks an order still moving: on the five
// statuses in flight, off the finished ones and the unknown.
// -----------------------------------------------------------

describe('StatusBadge — the dot of an order still moving', () => {

  it.each(IN_FLIGHT)('%s carries the dot', (status) => {
    expect(hasDot(badgeOf(status))).toBe(true)
  })


  it.each(FINISHED)('%s carries none — the order is finished', (status) => {
    expect(hasDot(badgeOf(status))).toBe(false)
  })


  it('a status it does not know carries none', () => {
    expect(hasDot(badgeOf(UNKNOWN))).toBe(false)
    expect(screen.getByText(UNKNOWN)).toBeInTheDocument()
  })
})
