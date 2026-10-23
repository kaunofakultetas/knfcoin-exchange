// -----------------------------------------------------------
//  [*] Test support — where the router is, and moving it
//
//  The pages navigate (the header's pills, the swap form's
//  submit, an order row, the way back from an order); a test
//  needs to see where a click took the student — the address
//  bar — and to tell a link the router follows from one it
//  leaves to the browser:
//
//    LocationProbe / currentPath — for renderPage (a memory
//                   router): the probe renders the router's
//                   pathname + search where currentPath
//                   reads it
//    navigateTo   — for renderApp (the BrowserRouter): what
//                   the browser's Forward or an address typed
//                   into the bar does — the History API plus
//                   the popstate the router listens to
//    goBack       — history.back(), inside act
//    followedByTheBrowser — whether a click on a link is left
//                   to the browser (a plain <a>, the explorer
//                   Caddy serves outside the SPA) rather than
//                   taken by the router
//
//  Under renderApp the address bar is window.location itself.
//
//  Used by:
//    - the component and page tests that render with
//      renderPage
//    - core/app.test.jsx, the Header and Home tests
// -----------------------------------------------------------

import { act, fireEvent, screen } from '@testing-library/react'
import { useLocation } from 'react-router-dom'







// -----------------------------------------------------------
// LocationProbe / currentPath
// -----------------------------------------------------------
//
// The probe is rendered beside the element under test, inside
// renderPage's memory router, and writes the router's pathname
// and search into a hidden output; currentPath reads it back,
// so a test can assert where a click took the student.
//
// Used by:
//   - the component and page tests that render with renderPage
// -----------------------------------------------------------

export function LocationProbe() {
  const { pathname, search } = useLocation()
  return <output data-testid="location" hidden>{pathname + search}</output>
}

export const currentPath = () => screen.getByTestId('location').textContent







// -----------------------------------------------------------
// navigateTo / goBack
// -----------------------------------------------------------
//
// navigateTo pushes a path onto the history and fires the
// popstate the router listens to; goBack is the browser's
// Back. Both run inside act. jsdom delivers history.back()'s
// popstate on a later task, so a test waits for the location
// after goBack.
//
// Used by:
//   - core/app.test.jsx — navigateTo, goBack
//   - pages/order/polling.test.jsx — navigateTo
// -----------------------------------------------------------

export async function navigateTo(path) {
  await act(async () => {
    window.history.pushState(null, '', path)
    window.dispatchEvent(new PopStateEvent('popstate', { state: null }))
  })
}

export async function goBack() {
  await act(async () => {
    window.history.back()
    await new Promise((resolve) => setTimeout(resolve, 20))
  })
}







// -----------------------------------------------------------
// followedByTheBrowser
// -----------------------------------------------------------
//
// Clicks a link and reports whether its default action — the
// browser loading the href — was left alone: true for a plain
// link, false for a router link, which prevents it and
// navigates inside the SPA instead. The click is seen last,
// on the window, after React's handler has had its say, and
// cancelled there either way, so jsdom never attempts the
// hard navigation it cannot perform.
//
// Used by:
//   - the Header and Home tests, core/app.test.jsx
// -----------------------------------------------------------

export function followedByTheBrowser(link) {
  let leftAlone = null
  const lastToSee = (event) => {
    leftAlone = !event.defaultPrevented
    event.preventDefault()
  }

  window.addEventListener('click', lastToSee)
  try {
    fireEvent.click(link)
  } finally {
    window.removeEventListener('click', lastToSee)
  }
  return leftAlone
}
