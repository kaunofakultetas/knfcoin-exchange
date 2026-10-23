// -----------------------------------------------------------
//  [*] Test support — rendering the way production frames it
//
//  The app needs no providers of its own: every page wraps
//  itself in the shared Layout, and main.jsx only puts the
//  App inside a BrowserRouter (under StrictMode). So the frame
//  a test gives is the router, nothing else:
//
//    renderPage — a page or component inside a MemoryRouter
//                 that starts at `route`, the element mounted
//                 on the route PATTERN (`path`) when it reads
//                 useParams, and a net that turns a render
//                 crash into a readable failure
//    renderApp  — the REAL App.jsx inside a BrowserRouter, the
//                 way main.jsx mounts it, started at a route
//                 through the History API
//
//  Both hand back Testing Library's result plus a userEvent
//  instance — whose setup also gives jsdom the clipboard it
//  lacks (CopyableAddress writes to it).
//
//  Used by:
//    - every component and page test, the App tests, the route
//      sweep
// -----------------------------------------------------------

import { Component } from 'react'
import { render } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { BrowserRouter, MemoryRouter, Route, Routes } from 'react-router-dom'
import App from '@/App.jsx'







// -----------------------------------------------------------
// TestErrorBoundary
// -----------------------------------------------------------
//
// Catches a render-time throw of the element under test and
// shows it as "render crashed: <message>" — so a page that
// cannot cope with a backend answer fails its test with the
// real message instead of an unhandled exception from deep
// inside React (contract.js' expectNoCrash reads it). The app
// itself has no error boundary; this one exists only in the
// tests.
//
// Used by:
//   - renderPage (below)
// -----------------------------------------------------------

export class TestErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  render() {
    if (this.state.error) {
      return <div data-testid="render-crashed">render crashed: {String(this.state.error?.message ?? this.state.error)}</div>
    }
    return this.props.children
  }
}







// -----------------------------------------------------------
// renderPage
// -----------------------------------------------------------
//
// Renders an element inside a memory router and returns
// Testing Library's result plus a userEvent instance. The
// router is Testing Library's `wrapper`, so a rerender keeps
// it — and the element's state — and only swaps the element.
//
// `route` is the router's initial entry, "/" unless the test
// names another. `path` is the route pattern the element is
// mounted on, so useParams reads its params from the route —
// the element then unmounts when the location leaves that
// pattern, as it would in the App; without it the element is
// rendered directly inside the router and stays whatever the
// location, which is what a test needs to watch a page
// navigate away (shell/router.jsx LocationProbe).
//
// Used by:
//   - component and page tests
// -----------------------------------------------------------

export function renderPage(ui, { route = '/', path } = {}) {
  const user = userEvent.setup()

  const Frame = ({ children }) => (
    <MemoryRouter initialEntries={[route]}>
      <TestErrorBoundary>{children}</TestErrorBoundary>
    </MemoryRouter>
  )
  const mounted = (element) => (path ? <Routes><Route path={path} element={element} /></Routes> : element)

  const result = render(mounted(ui), { wrapper: Frame })

  return { ...result, rerender: (next) => result.rerender(mounted(next)), user }
}







// -----------------------------------------------------------
// renderApp
// -----------------------------------------------------------
//
// The whole application: App.jsx with every route, inside the
// BrowserRouter main.jsx gives it, the location moved to
// `route` first (history.replaceState — jsdom keeps the
// origin). Only StrictMode is left out, so effects run once
// and a test can count the requests a route makes; the App
// tests mount it under StrictMode themselves.
//
// Used by:
//   - core/app.test.jsx, core/smoke.test.jsx, the route sweep
//   - components/footer.test.jsx — the footer in the shell
//   - pages/order/polling.test.jsx — moving between orders
// -----------------------------------------------------------

export function renderApp({ route = '/' } = {}) {
  window.history.replaceState(null, '', route)
  const user = userEvent.setup()

  const result = render(
    <BrowserRouter>
      <App />
    </BrowserRouter>
  )

  return { ...result, user }
}
