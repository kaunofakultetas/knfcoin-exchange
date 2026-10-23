// -----------------------------------------------------------
//  [*] Test support — the SPA's source, read as text
//
//  App.jsx declares its routes as JSX, not as an exported
//  object — so the structural rules and the route sweep read
//  them from the source text: every <Route> with its path,
//  index flag, element and redirect, and the page modules
//  App.jsx imports. A small brace-aware scanner, not a JSX
//  parser: it reads the shapes App.jsx uses and THROWS on
//  anything it cannot read, so a reshaped App.jsx fails
//  loudly instead of yielding an empty table every rule would
//  pass over.
//
//  Split into:
//
//    APP_ROOT / SRC   — where the app and its source live
//    readSource       — one file as text
//    sourceFiles      — every .js / .jsx / .mjs under a folder
//    withoutComments  — code with the comments blanked out
//    routeTags        — the <Route> tags of a JSX text
//    appRoutes        — every route of App.jsx, full paths
//    pageImports      — the page modules App.jsx imports
//
//  Used by:
//    - core/structural.test.js — every rule
//    - contract/route-sweep.test.jsx — the route table the
//      sweep must cover
// -----------------------------------------------------------

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'


// vitest runs from vite/app (the container's /app)
export const APP_ROOT = process.cwd()
export const SRC = join(APP_ROOT, 'src')







// -----------------------------------------------------------
// readSource / sourceFiles
// -----------------------------------------------------------
//
// readSource reads one file, named by its path under vite/app,
// as text. sourceFiles reads every .js, .jsx and .mjs file
// under a folder — src unless told otherwise — each with its
// path relative to vite/app and its text.
//
// Used by:
//   - appRoutes / pageImports (below)
//   - core/structural.test.js
// -----------------------------------------------------------

export const readSource = (path) => readFileSync(join(APP_ROOT, path), 'utf8')

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const full = join(dir, name)
  return statSync(full).isDirectory() ? walk(full) : [full]
})

export const sourceFiles = (dir = SRC) => walk(dir)
  .filter((full) => /\.(jsx?|mjs)$/.test(full))
  .map((full) => ({ file: relative(APP_ROOT, full), code: readFileSync(full, 'utf8') }))







// -----------------------------------------------------------
// withoutComments
// -----------------------------------------------------------
//
// Blanks out block comments (JSX's {/* … */} included) and
// line comments (a "//" right after a colon is a URL's, not a
// comment) — a banner that names a call or a route must not
// count as code.
//
// Used by:
//   - appRoutes / pageImports (below)
//   - core/structural.test.js — the call and storage scans
// -----------------------------------------------------------

export const withoutComments = (code) => code
  .replace(/\/\*[\s\S]*?\*\//g, '')
  .replace(/(^|[^:])\/\/.*$/gm, '$1')







// -----------------------------------------------------------
// routeTags
// -----------------------------------------------------------
//
// Every opening, self-closing and closing <Route> tag of a
// JSX text, in order: an opening tag with its attribute text
// and whether it closes itself, a closing tag as a bare mark.
// An opening tag ends at the first ">" outside braces and
// quotes — a redirect's element attribute, a <Navigate> with
// a quoted target, holds both. A <Routes> tag is never taken
// for one.
//
// Used by:
//   - appRoutes (below)
// -----------------------------------------------------------

function routeTags(jsx) {

  const tags = []

  for (let i = 0; i < jsx.length; i += 1) {
    if (jsx.startsWith('</Route>', i)) {
      tags.push({ close: true })
      continue
    }
    if (!jsx.startsWith('<Route', i) || !/[\s/>]/.test(jsx[i + 6])) continue

    let depth = 0
    let quote = null
    let end = i + 6
    for (; end < jsx.length; end += 1) {
      const c = jsx[end]
      if (quote) {
        if (c === quote) quote = null
      } else if (c === '"' || c === "'" || c === '`') {
        quote = c
      } else if (c === '{') {
        depth += 1
      } else if (c === '}') {
        depth -= 1
      } else if (c === '>' && depth === 0) {
        break
      }
    }

    const attrs = jsx.slice(i + 6, end)
    tags.push({ attrs, selfClosing: attrs.trimEnd().endsWith('/') })
    i = end
  }

  return tags
}







// -----------------------------------------------------------
// appRoutes
// -----------------------------------------------------------
//
// Every <Route> of App.jsx in declaration order, each with
// its path, whether it is an index route, the component it
// renders, and — for a <Navigate> — where it redirects and
// whether it replaces the history entry. A path is made
// absolute through its parents (an absolute one stands as it
// is, an index route carries its parent's path, the catch-all
// stays '*'). The component is the one named in the element
// attribute, null for a layout route that only groups
// children.
//
// Used by:
//   - core/structural.test.js — the route rules
//   - contract/route-sweep.test.jsx — the sweep's coverage
// -----------------------------------------------------------

export function appRoutes() {

  const tags = routeTags(withoutComments(readSource('src/App.jsx')))
  if (tags.length === 0) throw new Error('no <Route> found in src/App.jsx — has the route table moved?')

  const routes = []
  const parents = ['']
  const under = (parent, path) => (path.startsWith('/') ? path : `${parent.replace(/\/$/, '')}/${path}`)

  for (const tag of tags) {
    if (tag.close) {
      parents.pop()
      continue
    }

    const parent = parents[parents.length - 1]
    const path = tag.attrs.match(/\bpath="([^"]*)"/)?.[1] ?? null
    const index = /(^|\s)index(?=[\s/]|$)/.test(tag.attrs)
    const element = tag.attrs.match(/\belement=\{\s*<(\w+)/)?.[1] ?? null
    if (!index && path === null) throw new Error(`a <Route> with neither path nor index: <Route${tag.attrs}>`)

    const full = index ? (parent || '/') : (path === '*' ? '*' : under(parent, path))
    const navigate = element === 'Navigate' ? tag.attrs.match(/<Navigate\b[^>]*>/)?.[0] ?? '' : null
    routes.push({
      path: full,
      index,
      element,
      redirectTo: navigate === null ? null : (navigate.match(/\bto="([^"]*)"/)?.[1] ?? null),
      replace: navigate === null ? null : /\sreplace(?=[\s/>])/.test(navigate),
    })

    if (!tag.selfClosing) parents.push(full)
  }

  if (parents.length !== 1) throw new Error('unbalanced <Route> nesting in src/App.jsx')
  return routes
}







// -----------------------------------------------------------
// pageImports
// -----------------------------------------------------------
//
// Every page module App.jsx imports — the name it is imported
// under and the module's path under src/pages without its
// extension, read from the default imports of the .jsx files
// in src/pages.
//
// Used by:
//   - core/structural.test.js
// -----------------------------------------------------------

export function pageImports() {
  const app = withoutComments(readSource('src/App.jsx'))
  return [...app.matchAll(/^import (\w+) from '\.\/pages\/([^']+)\.jsx';?$/gm)].map(([, name, module]) => ({ name, module }))
}
