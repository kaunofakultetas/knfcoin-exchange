// -----------------------------------------------------------
//  [*] Test support — the vitest setup file
//
//  Runs before every test file (test.setupFiles in
//  vite.config.js):
//
//    - jest-dom matchers (toBeInTheDocument, toBeDisabled, …)
//    - the msw backend double (backend/server.js): started once
//      per file, handlers reset after every test, and a request
//      that no handler answers FAILS the test — a page calling
//      an endpoint the double does not know is exactly the kind
//      of drift this suite exists to catch
//    - a clean slate per test: DOM, URL (back to "/"), timers,
//      stubbed globals, environment variables (a test's TZ) and
//      mocks
//    - a console guard: React's own bug reports (a missing key,
//      a state update on another component while rendering, an
//      unknown DOM prop, a hook-order change) and jsdom's
//      refusal of a hard navigation (a test that clicked a
//      plain link and tested nothing) fail the test that
//      caused them; act() warnings are printed but tolerated —
//      a poll answering after the last assertion is not a
//      defect
//
//  No browser API needs a polyfill: jsdom covers everything
//  the app touches except the clipboard CopyableAddress writes
//  to, and that one comes from userEvent.setup() inside
//  renderPage / renderApp.
//
//  Nothing here reaches a real backend, browser or the network
//  — the whole suite is self-contained to vite/app.
// -----------------------------------------------------------

import '@testing-library/jest-dom/vitest'
import { afterAll, afterEach, beforeAll, beforeEach, vi } from 'vitest'
import { cleanup, configure } from '@testing-library/react'
import { server, unhandledRequests } from './backend/server'


// Messages console.error may carry that mean the code under
// test (or the test itself) has a bug — not a timing artefact
const FATAL_CONSOLE_PATTERNS = [
  /unique "key" prop/,
  /Cannot update a component .* while rendering a different component/,
  /Maximum update depth exceeded/,
  /React does not recognize the .* prop on a DOM element/,
  /Invalid DOM property/,
  /Rendered more hooks than during the previous render/,
  /Rendered fewer hooks than expected/,
  /Invalid hook call/,
  /Objects are not valid as a React child/,
  /Not implemented: navigation/,
]

// findBy*/waitFor give up after 1 s by default — too little for
// a page whose answers land on a loaded machine; nothing in
// the suite is meant to be timing-sensitive at that scale
configure({ asyncUtilTimeout: 5000 })







// -----------------------------------------------------------
// Backend double lifecycle
// -----------------------------------------------------------
//
// One msw server per test file: the default handlers (the
// happy path of every endpoint the SPA calls) come back after
// each test, so a test only ever declares the deviation it is
// about. A request no handler matched is recorded by
// backend/server.js and fails the test in afterEach — unless
// the test declared it expects one (allowUnhandledRequests).
//
// Used by:
//   - every test, implicitly
// -----------------------------------------------------------

let unhandledAllowed = false

export function allowUnhandledRequests() {
  unhandledAllowed = true
}


// A test that provokes one of the FATAL console messages on
// purpose declares the pattern(s) it expects — those lines
// are then not counted against it
const allowedConsoleErrors = []

export function allowConsoleErrors(...patterns) {
  allowedConsoleErrors.push(...patterns)
}


beforeAll(() => {
  server.listen({ onUnhandledRequest: 'bypass' })
})

afterAll(() => {
  server.close()
})







// -----------------------------------------------------------
// Per-test slate
// -----------------------------------------------------------
//
// Before: the URL back at "/", the console guard armed. After:
// React trees unmounted, handlers reset, real timers, stubbed
// globals, environment variables and mocks undone — then the
// unhandled-request and console verdicts, which come last so
// the cleanup has happened even when they fail the test.
//
// Used by:
//   - every test, implicitly
// -----------------------------------------------------------

const consoleErrors = []
let originalConsoleError

// jsdom reports what it cannot do (a hard navigation …) on
// its own virtual console, which vitest wires to the console
// that existed before the per-test one — a patched
// console.error never sees those reports, so the guard takes
// them from jsdom itself
globalThis.jsdom?.virtualConsole?.on('jsdomError', (error) => {
  consoleErrors.push(error.message)
})

beforeEach(() => {
  window.history.replaceState(null, '', '/')
  unhandledAllowed = false
  unhandledRequests.length = 0
  consoleErrors.length = 0
  allowedConsoleErrors.length = 0
  originalConsoleError = console.error
  console.error = (...args) => {
    consoleErrors.push(args.map((a) => (a instanceof Error ? a.message : String(a))).join(' '))
    originalConsoleError(...args)
  }
})

afterEach(async () => {
  cleanup()
  // jsdom queues a navigation with setImmediate — one turn lets
  // a hard navigation this test caused be reported against it,
  // not against the next test
  await new Promise((resolve) => setImmediate(resolve))
  server.resetHandlers()
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.unstubAllEnvs()
  vi.restoreAllMocks()
  console.error = originalConsoleError

  if (unhandledRequests.length && !unhandledAllowed) {
    const list = unhandledRequests.map((r) => `${r.method} ${r.url}`).join('\n  ')
    throw new Error(`request(s) the backend double has no handler for — add one in tests/support/backend/handlers.js or answer it in the test:\n  ${list}`)
  }

  const fatal = consoleErrors.filter((msg) =>
    FATAL_CONSOLE_PATTERNS.some((re) => re.test(msg)) && !allowedConsoleErrors.some((re) => re.test(msg)))
  if (fatal.length) {
    throw new Error(`console.error reported a defect during this test:\n  ${fatal.join('\n  ')}`)
  }
})
