// -----------------------------------------------------------
//  [*] Layout — the page shell
//
//  Shared page shell for every page in the playground (Home,
//  Exchange, Order and Reserves all render inside it):
//
//    - Background — fixed, layered gradient backdrop
//    - Header     — top navigation bar
//    - Footer     — bottom note
//    - a centered content column in between
//
//  All styling is Tailwind utilities plus a couple of inline
//  styles for the gradients that Tailwind cannot express -
//  there is deliberately no external stylesheet.
//
//  Used by:
//    - pages/Home/Home.jsx
//    - pages/Exchange/Exchange.jsx
//    - pages/Exchange/Order.jsx
//    - pages/Reserves/Reserves.jsx
// -----------------------------------------------------------

import { useLocation } from 'react-router-dom'
import Header from './Header.jsx'
import Footer from './Footer.jsx'







// -----------------------------------------------------------
// Background
// -----------------------------------------------------------
//
// Fixed full-screen backdrop behind the content, three layers
// back to front:
//
//   1. deep navy vertical gradient (base)
//   2. soft radial glows — indigo top-left, cyan top-right,
//      faint gold at the bottom (KNF's coin colour)
//   3. a dot grid that fades out towards the bottom
//
// Layered radial gradients and mask-image are not expressible
// as plain Tailwind utilities, so those two live in inline
// styles. The page itself wears the colour the base gradient
// starts and ends with (index.css), so scrolling past either
// end of a page shows no white.
//
// Used by:
//   - Layout (below)
// -----------------------------------------------------------

function Background() {
  return (
    <div className="fixed inset-0 -z-10" aria-hidden="true">

      {/* Base gradient + glow orbs */}
      <div
        className="absolute inset-0"
        style={{
          background:
            'radial-gradient(1100px 560px at 12% -8%, rgba(99,102,241,0.20), transparent 55%), ' +
            'radial-gradient(900px 480px at 88% -4%, rgba(34,211,238,0.12), transparent 55%), ' +
            'radial-gradient(700px 420px at 50% 110%, rgba(245,185,64,0.06), transparent 60%), ' +
            'linear-gradient(180deg, #06070f 0%, #0b0d1d 60%, #06070f 100%)',
        }}
      />

      {/* Dot grid, fading out towards the bottom */}
      <div
        className="absolute inset-0"
        style={{
          backgroundImage: 'radial-gradient(rgba(255,255,255,0.10) 1px, transparent 1px)',
          backgroundSize: '26px 26px',
          maskImage: 'linear-gradient(180deg, rgba(0,0,0,0.5), transparent 70%)',
          WebkitMaskImage: 'linear-gradient(180deg, rgba(0,0,0,0.5), transparent 70%)',
        }}
      />
    </div>
  )
}







// -----------------------------------------------------------
// Layout (default export)
// -----------------------------------------------------------
//
// Assembles the shell: background, header (told the current
// path so it can highlight the active nav link), the page
// content and the footer, all inside one centered column.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function Layout({ children }) {

  const location = useLocation()


  return (
    <div className="min-h-screen font-sans text-white/90 antialiased [color-scheme:dark] selection:bg-indigo-500/40">
      <Background />

      <div className="mx-auto max-w-[1100px] px-5 py-6 md:px-8">
        <Header currentPath={location.pathname} />

        <main>
          {children}
        </main>

        <Footer />
      </div>
    </div>
  )
}
