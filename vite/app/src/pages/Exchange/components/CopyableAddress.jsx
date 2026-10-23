// -----------------------------------------------------------
//  [*] CopyableAddress — an address with its copy button
//
//  A monospace address in a dark pill with a copy-to-clipboard
//  button that flips to "Copied" for a moment.
//
//  Used by:
//    - pages/Exchange/Order.jsx     — deposit + destination
//    - pages/Reserves/Reserves.jsx  — reserve wallet addresses
// -----------------------------------------------------------

import { useState } from 'react'







// -----------------------------------------------------------
// CopyableAddress (default export)
// -----------------------------------------------------------
//
// The address in full, free to wrap anywhere, beside its
// button: a click copies the exact string and the button
// says so for 1.5 seconds. A clipboard the browser blocks
// changes nothing on screen.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function CopyableAddress({ value }) {

  const [copied, setCopied] = useState(false)


  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // Clipboard blocked (e.g. insecure context) — nothing else to do.
    }
  }


  return (
    <div className="flex w-fit max-w-full items-center gap-2 rounded-xl border border-white/[0.12] bg-black/25 py-2 pl-3 pr-2">
      <span className="break-all font-mono text-[13px] leading-snug">{value}</span>
      <button
        type="button"
        onClick={handleCopy}
        className={
          'shrink-0 rounded-lg border px-2.5 py-1.5 text-xs font-semibold transition-colors ' +
          (copied
            ? 'border-emerald-400/50 bg-emerald-500/15 text-emerald-300'
            : 'border-white/[0.16] bg-white/[0.08] text-white/80 hover:border-indigo-400/60')
        }
      >
        {copied ? 'Copied ✓' : 'Copy'}
      </button>
    </div>
  )
}
