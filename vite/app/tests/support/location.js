// -----------------------------------------------------------
//  [*] Test support — the origin the SPA runs on
//
//  jsdom's origin is pinned (vitest's default,
//  http://localhost:3000). ExchangeApi fetches relative
//  "/api/exchange/…" paths; msw resolves a relative URL
//  against the page's location the way a browser does, so the
//  requests land on this origin, where the msw handlers
//  listen (TEST_ORIGIN).
//
//  Routing needs no double: main.jsx mounts the App inside a
//  BrowserRouter, which jsdom supports through the History
//  API — tests set the start path with history.replaceState
//  (see render.jsx renderApp). What jsdom cannot do is a HARD
//  navigation, the one the plain links to /explorer/ leave to
//  the browser — shell/router.jsx tells such a link from a
//  router link without following it.
//
//  Used by:
//    - backend/server.js, backend/handlers.js — TEST_ORIGIN
//    - core/structural.test.js — the handlers' paths
//    - lib/api.test.js — the URL of an encoded order id
// -----------------------------------------------------------

// Where every request of the SPA lands in the suite
export const TEST_ORIGIN = 'http://localhost:3000'
