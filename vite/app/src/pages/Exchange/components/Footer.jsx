// -----------------------------------------------------------
//  [*] Footer — the note at the bottom of every page
//
//  Bottom note on every page: copyright plus a reminder that
//  everything traded here is a valueless testnet coin.
//
//  Used by:
//    - components/Layout.jsx
// -----------------------------------------------------------







// -----------------------------------------------------------
// Footer (default export)
// -----------------------------------------------------------
//
// The two lines, centred under the page: the copyright,
// dated with the current year, then the testnet reminder.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function Footer() {
  return (
    <footer className="mt-14 flex flex-col items-center gap-1 border-t border-white/[0.07] pt-6 pb-2 text-center text-xs text-white/45">
      <span>© {new Date().getFullYear()} VU KNF Coin Exchange — Vilnius university Kaunas faculty</span>
      <span>Testnet coins only — KNF Coin and Litecoin Testnet4 have no real-world value.</span>
    </footer>
  )
}
