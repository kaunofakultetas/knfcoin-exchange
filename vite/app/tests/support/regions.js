// -----------------------------------------------------------
//  [*] Test support — the parts of a page that have no
//      landmark of their own
//
//  The pages are built from plain divs and spans: a swap
//  panel or a reserve card carries no role, label or test id
//  a query could take hold of. Rather than
//  reaching for class names, a test names a text the student
//  reads in that part and lets these helpers find the part
//  around it — so a restyled page keeps its tests, and only a
//  page whose words change breaks them:
//
//    regionAround  — the nearest element around a text that
//                    meets a condition
//    regionHolding — the nearest element around a text that
//                    also holds every other text given
//    wholeText     — a matcher for a sentence split across
//                    elements (a <strong> inside it)
//
//  Used by:
//    - the page and component tests
// -----------------------------------------------------------

import { screen } from '@testing-library/react'







// -----------------------------------------------------------
// regionAround
// -----------------------------------------------------------
//
// Starts at the element showing `text` (exactly, as
// getByText finds it) and climbs to the first element — that
// one included — for which `holds` is true; throws when no
// ancestor does, so a region that disappeared fails loudly.
// `text` may also be an element to start from.
//
// Used by:
//   - regionHolding (below)
//   - support/exchange/page.jsx — a swap panel
// -----------------------------------------------------------

export function regionAround(text, holds) {
  let node = typeof text === 'string' ? screen.getByText(text) : text
  while (node && !holds(node)) node = node.parentElement
  if (!node) throw new Error(`nothing around "${text}" meets the condition`)
  return node
}







// -----------------------------------------------------------
// regionHolding
// -----------------------------------------------------------
//
// The smallest element around `text` whose content also
// includes every one of `others` — a card named by its
// heading and recognised by a label every card carries.
//
// Used by:
//   - pages/reserves.test.jsx — a chain's card
// -----------------------------------------------------------

export function regionHolding(text, ...others) {
  return regionAround(text, (node) => others.every((other) => node.textContent.includes(other)))
}







// -----------------------------------------------------------
// wholeText
// -----------------------------------------------------------
//
// A Testing Library matcher for an element whose whole text —
// its descendants' included, whitespace collapsed — reads
// exactly `text`, the innermost such element only: a sentence
// with a <strong> inside is one thing the student reads,
// though getByText would see it in pieces.
//
// Used by:
//   - the tests that find a page by its headline — the home
//     page's puts a space at the start of an inner span, which
//     the accessible name drops: core/app.test.jsx,
//     core/smoke.test.jsx, pages/home.test.jsx,
//     contract/route-sweep.test.jsx
//   - pages/order/summary.test.jsx — the deposit instruction
// -----------------------------------------------------------

export function wholeText(text) {
  const reads = (node) => node.textContent.replace(/\s+/g, ' ').trim() === text
  return (_, element) => Boolean(element) && reads(element) && ![...element.children].some(reads)
}
