// -----------------------------------------------------------
//  [*] Tests — structural rules of the SPA
//
//  Rules about the code base as a whole rather than one
//  component, read from the source text:
//    - the backend calls: ExchangeApi (lib/api.js) is the one
//      way to the backend — its http() holds the only fetch,
//      every endpoint it calls is a relative /api/exchange
//      path with a default handler in the test double, no page
//      or component fetches on its own, and nothing else talks
//      to the network
//    - the route table: every page module under src/pages is
//      imported statically by App.jsx and routed, each a
//      default-exported component that renders inside the
//      shared Layout; anything else redirects home with a
//      replace; the block explorer Caddy serves at /explorer/
//      is never a route and only ever a plain link
//    - the order statuses: the double's orders cover every
//      status of lib/orders.js and use no other
//    - the answers: every field ExchangeApi reads off an order
//      or a reserve, every rate key the pages look up and the
//      limits of both assets are in the double's answers, in
//      the units the pages compute with — amounts as numbers
//      of whole coins, times as epoch milliseconds — and each
//      coin has one logo, the same in every answer. This is
//      the frontend's half of the contract; the backend's
//      suite holds its own written copy and checks the real
//      answers against it (backend/tests/contract.py)
//    - index.html: English, titled like the brand, the #root
//      main.jsx mounts into — the page itself the colour the
//      backdrop starts and ends with
//    - the static files the pages point at — the brand's
//      logo, the favicon — are in public/
//    - the SPA keeps nothing in the browser — the backend is
//      the single source of truth for orders (lib/orders.js'
//      header)
// -----------------------------------------------------------

import { describe, it, expect } from 'vitest'
import { existsSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { defaultHandlers } from '../support/backend/handlers'
import { TEST_ORIGIN } from '../support/location'
import * as f from '../support/backend/fixtures'
import { APP_ROOT, SRC, appRoutes, pageImports, readSource, sourceFiles, withoutComments } from '../support/shell/source'
import { ORDER_STATUS } from '@/pages/Exchange/lib/orders.js'


// The code of every source file, comments blanked out
const CODE = sourceFiles().map(({ file, code }) => ({ file, code: withoutComments(code) }))

// The one module that talks to the backend
const API_MODULE = 'src/pages/Exchange/lib/api.js'







// -----------------------------------------------------------
// callArguments
// -----------------------------------------------------------
//
// The argument list of the call whose "(" sits at `open`, as
// top-level arguments — strings, templates and nested
// brackets respected.
// -----------------------------------------------------------

function callArguments(code, open) {

  const args = []
  let depth = 0
  let quote = null
  let start = open + 1

  for (let i = open; i < code.length; i += 1) {
    const c = code[i]
    if (quote) {
      if (c === '\\') i += 1
      else if (c === quote) quote = null
      continue
    }
    if (c === '"' || c === "'" || c === '`') quote = c
    else if ('([{'.includes(c)) depth += 1
    else if (')]}'.includes(c)) {
      depth -= 1
      if (depth === 0) {
        args.push(code.slice(start, i).trim())
        return args.filter(Boolean)
      }
    } else if (c === ',' && depth === 1) {
      args.push(code.slice(start, i).trim())
      start = i + 1
    }
  }
  throw new Error(`unclosed call at ${open}`)
}







// -----------------------------------------------------------
// backendCalls
// -----------------------------------------------------------
//
// Every call of ExchangeApi's http helper and every fetch in
// src/ (their definitions left out), each with its file. A
// call of http names its method and URL: a literal or
// template URL becomes its path, with template expressions
// turned into ":param" and the query string dropped. A fetch
// keeps the expression its URL comes from.
// -----------------------------------------------------------

const CALL_RE = /(?<!function\s+)(?<![\w.$])(http|fetch)\(/g

function backendCalls() {

  const calls = []

  for (const { file, code } of CODE) {
    for (const match of code.matchAll(CALL_RE)) {
      const args = callArguments(code, match.index + match[0].length - 1)

      if (match[1] === 'fetch') {
        calls.push({ file, via: 'fetch', expression: args[0] ?? '' })
        continue
      }

      const method = args[0]?.match(/^'(\w+)'$/)?.[1]
      const literal = args[1]?.match(/^(?:"([^"]*)"|'([^']*)'|`([^`]*)`)$/)
      if (!method || !literal) throw new Error(`an http() call in ${file} this rule cannot read: http(${args.join(', ')})`)
      const raw = literal[1] ?? literal[2] ?? literal[3]
      calls.push({ file, via: 'http', method, url: raw.replace(/\$\{[^}]*\}/g, ':param').split('?')[0] })
    }
  }

  return calls
}

// A handler's path (absolute, msw params) against a call's
// path: segment-wise, a ":param" on either side matching
// anything
const handlerMatches = (handler, method, url) => {
  if (handler.info.method.toUpperCase() !== method) return false
  const hs = String(handler.info.path).replace(TEST_ORIGIN, '').split('/')
  const cs = url.split('/')
  if (hs.length !== cs.length) return false
  return hs.every((segment, i) => segment.startsWith(':') || cs[i].startsWith(':') || segment === cs[i])
}







// -----------------------------------------------------------
// pageModules
// -----------------------------------------------------------
//
// The page modules on disk: every .jsx file directly inside a
// folder of src/pages, as its path under src/pages without
// the extension. The folders' components/ and lib/ hold what
// the pages share, not pages.
// -----------------------------------------------------------

function pageModules() {
  const pages = join(SRC, 'pages')
  return readdirSync(pages)
    .filter((dir) => statSync(join(pages, dir)).isDirectory())
    .flatMap((dir) => readdirSync(join(pages, dir))
      .filter((name) => name.endsWith('.jsx') && statSync(join(pages, dir, name)).isFile())
      .map((name) => `${dir}/${name.replace(/\.jsx$/, '')}`))
    .sort()
}







// -----------------------------------------------------------
// fieldsRead
// -----------------------------------------------------------
//
// The fields ExchangeApi reads off one answer: every
// `<param>.<field>` inside the named camelize function of
// lib/api.js, in the order it reads them. Throws when the
// function is gone, so a reshaped client fails the rules
// loudly instead of yielding an empty list.
// -----------------------------------------------------------

function fieldsRead(name, param) {
  const code = withoutComments(readSource(API_MODULE))
  const body = code.match(new RegExp(`function ${name}\\(${param}\\) \\{([\\s\\S]*?)\\n\\}`))?.[1]
  if (!body) throw new Error(`${name}(${param}) not found in ${API_MODULE}`)
  return [...new Set([...body.matchAll(new RegExp(`\\b${param}\\.(\\w+)`, 'g'))].map((match) => match[1]))]
}

// The asset labels the swap form shows, read from its constants
const assetLabels = () => {
  const exchange = withoutComments(readSource('src/pages/Exchange/Exchange.jsx'))
  return ['KNF', 'LTCT'].map((name) => exchange.match(new RegExp(`const ${name} = '([^']+)'`))?.[1])
}







// -----------------------------------------------------------
// The backend calls
// -----------------------------------------------------------
//
// Every call the SPA makes to the backend lives in
// lib/api.js, has a default handler in the test double and
// uses a relative /api/exchange path — nothing else in src/
// reaches the network.
// -----------------------------------------------------------

describe('structural rules — the backend calls', () => {

  const calls = backendCalls()


  it('finds the five endpoints ExchangeApi calls, and the one fetch behind them', () => {
    expect(calls.filter((call) => call.via === 'http').map(({ method, url }) => `${method} ${url}`).sort()).toEqual([
      'GET /api/exchange/orders',
      'GET /api/exchange/orders/:param',
      'GET /api/exchange/rates',
      'GET /api/exchange/reserves',
      'POST /api/exchange/orders',
    ])
    expect(calls.filter((call) => call.via === 'fetch')).toEqual([{ file: API_MODULE, via: 'fetch', expression: 'path' }])
  })


  it('every backend call in src/ has a default handler in the test double', () => {
    const unhandled = calls
      .filter((call) => call.url && !defaultHandlers.some((handler) => handlerMatches(handler, call.method, call.url)))
      .map((call) => `${call.method} ${call.url} (${call.file})`)
    expect(unhandled).toEqual([])
  })


  it('every URL is a relative /api/exchange path — no hardcoded host', () => {
    const elsewhere = calls.filter((call) => call.url && !call.url.startsWith('/api/exchange/')).map((call) => `${call.url} (${call.file})`)
    expect(elsewhere).toEqual([])
  })


  it('no page or component reaches the backend on its own — every call lives in lib/api.js', () => {
    expect(calls.filter((call) => call.file !== API_MODULE)).toEqual([])
    for (const page of ['Home/Home', 'Exchange/Exchange', 'Exchange/Order', 'Reserves/Reserves']) {
      expect(readSource(`src/pages/${page}.jsx`), page).toMatch(/import \{ ExchangeApi \} from '\.\.?\/(Exchange\/)?lib\/api\.js'/)
    }
  })


  it('nothing else talks to the network — no XMLHttpRequest, WebSocket, EventSource, beacon or axios', () => {
    const offenders = CODE.filter(({ code }) => (
      /\bnew\s+(XMLHttpRequest|WebSocket|EventSource)\b|\bsendBeacon\(|\baxios\b/.test(code)
    )).map(({ file }) => file)
    expect(offenders).toEqual([])
  })
})







// -----------------------------------------------------------
// The route table
// -----------------------------------------------------------
//
// App.jsx's routes, read from its source: every page module
// imported, routed and rendered inside the shared Layout, the
// catch-all sending anything else home, /explorer/ left to
// Caddy.
// -----------------------------------------------------------

describe('structural rules — the route table', () => {

  it('reads App.jsx\'s routes', () => {
    expect(appRoutes()).toEqual([
      { path: '/', index: false, element: 'Home', redirectTo: null, replace: null },
      { path: '/exchange', index: false, element: 'Exchange', redirectTo: null, replace: null },
      { path: '/exchange/order/:orderId', index: false, element: 'Order', redirectTo: null, replace: null },
      { path: '/reserves', index: false, element: 'Reserves', redirectTo: null, replace: null },
      { path: '*', index: false, element: 'Navigate', redirectTo: '/', replace: true },
    ])
  })


  it('imports every page module under src/pages statically, and routes it', () => {
    const imports = pageImports()
    const routed = new Set(appRoutes().map((route) => route.element))

    expect(imports.map((entry) => entry.module).sort()).toEqual(pageModules())
    for (const { name, module } of imports) {
      expect(routed.has(name), `${module} (${name}) is a route's element`).toBe(true)
    }
  })


  it('every page module default-exports its component', () => {
    for (const module of pageModules()) {
      expect(readSource(`src/pages/${module}.jsx`), module).toMatch(/^export default function \w+\(/m)
    }
  })


  it('every page renders inside the shared Layout', () => {
    for (const module of pageModules()) {
      const code = withoutComments(readSource(`src/pages/${module}.jsx`))
      expect(code, module).toMatch(/^import Layout from '[./]+(Exchange\/)?components\/Layout\.jsx'/m)
      expect(code, module).toMatch(/<Layout>/)
    }
  })


  it('sends anything else home, replacing the history entry — the catch-all coming last', () => {
    const routes = appRoutes()
    const catchAll = routes.find((route) => route.path === '*')
    expect(catchAll).toMatchObject({ element: 'Navigate', redirectTo: '/', replace: true })
    expect(routes.at(-1)).toBe(catchAll)
  })


  it('leaves /explorer/ to Caddy: no route claims it, and every link to it is a plain one', () => {
    expect(appRoutes().filter((route) => route.path.startsWith('/explorer'))).toEqual([])

    const routerLinks = CODE.filter(({ code }) => /\bto=["'{`]+\/explorer/.test(code)).map(({ file }) => file)
    expect(routerLinks).toEqual([])

    const plainLinks = CODE.flatMap(({ file, code }) => [...code.matchAll(/href="\/explorer\/"/g)].map(() => file))
    expect(plainLinks.sort()).toEqual(['src/pages/Exchange/components/Header.jsx', 'src/pages/Home/Home.jsx'])
  })
})







// -----------------------------------------------------------
// The order statuses
// -----------------------------------------------------------
//
// The double's orders cover exactly the statuses
// lib/orders.js names.
// -----------------------------------------------------------

describe('structural rules — the order statuses', () => {

  it('the double\'s orders cover every status of lib/orders.js, and use no other', () => {
    const used = new Set(f.orders().map((row) => row.status))
    expect([...used].sort()).toEqual(Object.values(ORDER_STATUS).sort())
  })
})







// -----------------------------------------------------------
// The answers the SPA reads
// -----------------------------------------------------------
//
// A field the pages read but the double never answers would
// leave every page test blind to it; these rules keep the
// double complete as the client grows.
// -----------------------------------------------------------

describe('structural rules — the answers the SPA reads', () => {

  const ORDER_FIELDS = fieldsRead('camelizeOrder', 'o')
  const REFUND_FIELDS = fieldsRead('camelizeRefund', 'refund')
  const RECIPIENT_FIELDS = fieldsRead('camelizeRecipient', 'recipient')
  const RESERVE_FIELDS = fieldsRead('camelizeReserve', 'r')
  const ROWS = [...f.orders(), f.createdOrder()]
  const REFUNDS = ROWS.flatMap((row) => row.refunds)


  it('finds the fields ExchangeApi reads off an order, its refunds and a reserve', () => {
    expect(ORDER_FIELDS).toEqual([
      'id', 'pair', 'from_asset', 'to_asset', 'from_amount', 'to_amount', 'rate', 'locked_rate',
      'destination', 'status', 'confirm_target', 'confirm_count', 'deposit_address', 'deposit_scripthash',
      'received_amount', 'tx_deposit_id', 'tx_send_id', 'error', 'from_icon', 'to_icon', 'refunds', 'created_at',
      'updated_at', 'expires_at',
    ])
    expect(REFUND_FIELDS).toEqual(['txid', 'confirmed', 'created_at', 'recipients'])
    expect(RECIPIENT_FIELDS).toEqual(['address', 'amount'])
    expect(RESERVE_FIELDS).toEqual([
      'network', 'asset', 'short_name', 'full_name', 'block_explorer', 'icon', 'address', 'confirmed', 'unconfirmed',
      'available', 'error',
    ])
  })


  it('the double answers every order field the SPA reads — in every row, and in the order it creates', () => {
    for (const row of ROWS) {
      expect(ORDER_FIELDS.filter((field) => !Object.hasOwn(row, field)), row.id).toEqual([])
    }
  })


  it('the double answers every refund field the SPA reads — and has refunds to answer them with', () => {
    expect(REFUNDS.length).toBeGreaterThan(0)
    for (const refund of REFUNDS) {
      expect(REFUND_FIELDS.filter((field) => !Object.hasOwn(refund, field)), refund.txid).toEqual([])
      for (const recipient of refund.recipients) {
        expect(RECIPIENT_FIELDS.filter((field) => !Object.hasOwn(recipient, field)), refund.txid).toEqual([])
      }
    }
  })


  it('the double answers every reserve field the SPA reads', () => {
    for (const reserve of f.reserves()) {
      expect(RESERVE_FIELDS.filter((field) => !Object.hasOwn(reserve, field)), reserve.network).toEqual([])
    }
  })


  it('the double keys the rates and the limits the way the pages look them up', () => {
    const labels = assetLabels()
    expect(labels).toEqual(['KNF Coin', 'LTC Testnet'])

    // The swap form looks a pair up as "<from>-><to>", the home page's
    // chip by its one literal
    const keys = [`${labels[0]}->${labels[1]}`, `${labels[1]}->${labels[0]}`]
    const homeKey = withoutComments(readSource('src/pages/Home/Home.jsx')).match(/pairs\?\.\['([^']+)'\]/)?.[1]
    expect(Object.keys(f.rates.pairs).sort()).toEqual([...keys].sort())
    expect(keys).toContain(homeKey)

    expect(Object.keys(f.rates.limits).sort()).toEqual([...labels].sort())
    for (const label of labels) {
      expect(f.rates.limits[label], label).toEqual({ min: expect.any(Number), max: expect.any(Number) })
    }

    // What can still be paid out, looked up by the asset received
    expect(Object.keys(f.rates.capacity).sort()).toEqual([...labels].sort())
    for (const label of labels) {
      expect(f.rates.capacity[label], label).toEqual(expect.any(Number))
    }
  })


  it('the double speaks the units the pages compute with: whole coins as numbers, times as epoch milliseconds', () => {
    for (const row of ROWS) {
      for (const field of ['from_amount', 'to_amount', 'rate', 'received_amount']) {
        expect(typeof row[field], `${row.id}.${field}`).toBe('number')
      }
      for (const field of ['confirm_target', 'confirm_count']) {
        expect(Number.isInteger(row[field]), `${row.id}.${field}`).toBe(true)
      }
      // A time in seconds would read as January 1970 to the countdown
      for (const field of ['created_at', 'updated_at', 'expires_at']) {
        expect(Number.isInteger(row[field]) && row[field] > 1e12, `${row.id}.${field}`).toBe(true)
      }
    }
    for (const reserve of f.reserves()) {
      for (const field of ['confirmed', 'unconfirmed', 'available']) {
        expect(typeof reserve[field], `${reserve.network}.${field}`).toBe('number')
      }
    }
    for (const refund of REFUNDS) {
      expect(typeof refund.confirmed, refund.txid).toBe('boolean')
      expect(Number.isInteger(refund.created_at) && refund.created_at > 1e12, refund.txid).toBe(true)
      for (const recipient of refund.recipients) {
        expect(typeof recipient.amount, refund.txid).toBe('number')
      }
    }
  })


  it('the double advertises one logo per coin, the same in every answer', () => {
    const labels = assetLabels()
    expect(Object.keys(f.rates.icons).sort()).toEqual([...labels].sort())
    for (const label of labels) {
      expect(f.rates.icons[label], label).toMatch(/^\/api\/exchange\/icons\/\w+$/)
    }
    for (const row of ROWS) {
      expect([row.from_icon, row.to_icon], row.id).toEqual([f.rates.icons[row.from_asset], f.rates.icons[row.to_asset]])
    }
    for (const reserve of f.reserves()) {
      expect(reserve.icon, reserve.network).toBe(f.rates.icons[reserve.asset])
      expect(reserve.icon, reserve.network).toBe(`/api/exchange/icons/${reserve.network}`)
    }
  })


  it('the double\'s assets are the labels the pages show', () => {
    const labels = assetLabels()
    for (const row of ROWS) {
      expect(labels, row.id).toContain(row.from_asset)
      expect(labels, row.id).toContain(row.to_asset)
    }
    expect(f.reserves().map((reserve) => reserve.asset).sort()).toEqual([...labels].sort())
  })
})







// -----------------------------------------------------------
// index.html
// -----------------------------------------------------------
//
// The page main.jsx mounts into: English, titled like the
// brand, the App inside a BrowserRouter under StrictMode —
// and the page itself, past the ends of the app's backdrop,
// the colour that backdrop starts and ends with, not the
// browser's white.
// -----------------------------------------------------------

describe('structural rules — index.html', () => {

  it('declares the page English, titles it like the brand and holds the #root main.jsx renders into', () => {
    const html = readSource('index.html')
    expect(html).toMatch(/<html lang="en">/)
    expect(html.match(/<title>([^<]*)<\/title>/)?.[1]).toBe('VU KNF Coin Exchange')
    expect(html).toMatch(/<div id="root"><\/div>/)
    expect(html).toMatch(/<script type="module" src="\/src\/main\.jsx"><\/script>/)
    expect(readSource('src/main.jsx')).toMatch(/createRoot\(document\.getElementById\('root'\)\)/)
  })


  it('main.jsx mounts the App inside a BrowserRouter, under StrictMode', () => {
    const main = withoutComments(readSource('src/main.jsx')).replace(/\s+/g, ' ')
    expect(main).toMatch(/<StrictMode> <BrowserRouter> <App \/> <\/BrowserRouter> <\/StrictMode>/)
  })


  it('the page wears the colour the backdrop starts and ends with — scrolling past it shows no white', () => {
    const edge = readSource('src/pages/Exchange/components/Layout.jsx').match(/linear-gradient\(180deg, (#[0-9a-f]{6}) 0%, .*?, \1 100%\)/)?.[1]
    const css = withoutComments(readSource('src/index.css')).replace(/\s+/g, ' ')
    expect(edge, 'the backdrop starts and ends with one colour').toBeTruthy()
    expect(css).toContain(`html { background-color: ${edge}; color-scheme: dark; }`)
  })
})







// -----------------------------------------------------------
// The files the SPA ships
// -----------------------------------------------------------
//
// Every static file the pages point at — the brand's logo,
// the favicon — lies in public/, which the build copies as it
// is: a renamed or deleted file fails here instead of showing
// a broken image.
// -----------------------------------------------------------

describe('structural rules — the files the SPA ships', () => {

  // Every path under /img a source file names, in quotes
  const IMAGE_PATH = /['"`](\/img\/[^'"`?#\s]+)['"`]/g


  it('every image the source points at under /img is in public/', () => {
    const paths = CODE.flatMap(({ code }) => [...code.matchAll(IMAGE_PATH)].map((match) => match[1]))
    expect(paths).toContain('/img/logo_knfcoin.svg')
    for (const path of paths) {
      expect(existsSync(join(APP_ROOT, 'public', path)), path).toBe(true)
    }
  })


  it('the favicon index.html names is in public/', () => {
    const href = readSource('index.html').match(/<link rel="icon"[^>]*href="\/([^"]+)"/)?.[1]
    expect(href).toBeTruthy()
    expect(existsSync(join(APP_ROOT, 'public', href)), href).toBe(true)
  })
})







// -----------------------------------------------------------
// What the SPA remembers
// -----------------------------------------------------------
//
// Nothing kept in the browser: the backend is the single
// source of truth for orders.
// -----------------------------------------------------------

describe('structural rules — what the SPA remembers', () => {

  it('keeps nothing in the browser — no localStorage, sessionStorage, cookie, IndexedDB or Cache API', () => {
    const offenders = CODE.filter(({ code }) => (
      /\blocalStorage\b|\bsessionStorage\b|document\.cookie|\bindexedDB\b|\bcaches\./.test(code)
    )).map(({ file }) => file)
    expect(offenders).toEqual([])
  })
})
