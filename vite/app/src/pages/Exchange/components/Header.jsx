// -----------------------------------------------------------
//  [*] Header — the navigation bar
//
//  Top navigation bar shown on every page:
//    - brand mark (the KNF Coin logo + "KNF Exchange"); the
//      logo is a file of the SPA itself (public/img), so it
//      shows whatever state the backend is in
//    - nav pills: Home, Exchange, Reserves (React Router
//      links) and Explorer (a plain link, served by Caddy
//      outside the SPA)
//
//  The pill of the tool the student is on is highlighted, on
//  the tool's own page and on every page under it (an order's
//  page belongs to Exchange), so students always know which
//  tool they are on.
//
//  Used by:
//    - components/Layout.jsx — passes the current path down
// -----------------------------------------------------------

import { Link } from 'react-router-dom'







// -----------------------------------------------------------
// isOnTool
// -----------------------------------------------------------
//
// Whether the current path is the tool's own page or a page
// under it. Home is the exception: every path sits under "/",
// so its pill matches the home page alone. A plain link (the
// Explorer, outside the SPA) has no path here and never
// matches.
//
// Used by:
//   - NavPill (below)
// -----------------------------------------------------------

function isOnTool(to, currentPath) {
  if (!to || !currentPath) return false
  if (to === '/') return currentPath === '/'
  return currentPath === to || currentPath.startsWith(`${to}/`)
}







// -----------------------------------------------------------
// NavPill
// -----------------------------------------------------------
//
// One nav entry: an in-app router link when given `to`, a
// plain link when given `href` (for /explorer/, which React
// Router does not own). Highlighted while the student is on
// its tool.
//
// Used by:
//   - Header (below)
// -----------------------------------------------------------

function NavPill({ to, href, label, currentPath }) {

  const isActive = isOnTool(to, currentPath)


  const className =
    'rounded-full px-3 py-2 text-sm font-semibold transition-colors sm:px-4 ' +
    (isActive
      ? 'bg-indigo-500/25 text-indigo-200 ring-1 ring-indigo-400/40'
      : 'text-white/70 hover:bg-white/[0.07] hover:text-white')


  if (href) {
    return <a href={href} className={className}>{label}</a>
  }

  return <Link to={to} className={className}>{label}</Link>
}







// -----------------------------------------------------------
// Header (default export)
// -----------------------------------------------------------
//
// The brand mark leading home, then the four pills, each told
// the current path to decide its own highlight — on a narrow
// screen the pills take a row of their own under the brand.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function Header({ currentPath }) {
  return (
    <header className="mb-8 flex flex-wrap items-center justify-between gap-x-4 gap-y-3">

      {/* Brand */}
      <Link to="/" className="flex items-center gap-2.5">
        <img src="/img/logo_knfcoin.svg" alt="" className="h-9 w-9 flex-none rounded-full shadow-lg shadow-black/30" />
        <span className="text-lg font-extrabold tracking-tight text-white">
          KNF <span className="bg-gradient-to-r from-indigo-300 to-cyan-300 bg-clip-text text-transparent">Exchange</span>
        </span>
      </Link>

      {/* Navigation */}
      <nav className="flex w-full items-center justify-between gap-1 rounded-full border border-white/10 bg-white/[0.04] p-1 backdrop-blur-md sm:w-auto sm:justify-start">
        <NavPill to="/" label="Home" currentPath={currentPath} />
        <NavPill to="/exchange" label="Exchange" currentPath={currentPath} />
        <NavPill to="/reserves" label="Reserves" currentPath={currentPath} />
        <NavPill href="/explorer/" label="Explorer" currentPath={currentPath} />
      </nav>
    </header>
  )
}
