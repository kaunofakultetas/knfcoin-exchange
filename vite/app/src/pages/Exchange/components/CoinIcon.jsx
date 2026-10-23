// -----------------------------------------------------------
//  [*] CoinIcon — the mark of a coin
//
//  Renders the coin's logo when the backend advertises one (a
//  file the operator dropped into the mounted _CONFIG/icons
//  folder — every answer that names a coin carries its
//  /api/exchange/icons/... URL); otherwise, or if the image
//  fails to load, a round dot in a colour derived from the
//  coin's label — so a coin without a logo stays recognizable
//  instead of broken, and every place in the app shows the
//  SAME mark for the same coin.
//
//  Split into (root component last):
//
//    colorFromString — a stable fallback colour per label
//    CoinIcon        — logo with dot fallback (default
//                      export)
//
//  Used by:
//    - pages/Exchange/Exchange.jsx — swap panels, recent orders
//    - pages/Exchange/Order.jsx    — order summary header
//    - pages/Reserves/Reserves.jsx — each reserve card
// -----------------------------------------------------------

import { useState } from 'react'


// The dot of a mark with no label to colour it by
const NEUTRAL_GREY = '#9e9e9e'







// -----------------------------------------------------------
// colorFromString
// -----------------------------------------------------------
//
// A stable vivid colour from any string: its hash picks the
// hue, saturation and lightness stay fixed — so each coin
// gets its own recognizable dot without anyone maintaining a
// palette, and no label at all gets the neutral grey.
//
// Used by:
//   - CoinIcon (below)
// -----------------------------------------------------------

function colorFromString(input) {
  if (!input) return NEUTRAL_GREY

  let hash = 0
  for (let i = 0; i < input.length; i += 1) {
    hash = (hash << 5) - hash + input.charCodeAt(i)
    hash |= 0 // keep it a 32bit integer
  }

  const hue = Math.abs(hash) % 360
  return `hsl(${hue}, 65%, 55%)`
}







// -----------------------------------------------------------
// CoinIcon (default export)
// -----------------------------------------------------------
//
// One coin's mark at the requested pixel size, never squeezed
// by the row it sits in. The logo URL is the one the backend
// advertises, or nothing; the coin's label seeds the fallback
// colour, so every page shows the same dot for the same coin.
// The logo is decorative — the coin's name always stands
// beside it.
//
// Used by:
//   - see the file header
// -----------------------------------------------------------

export default function CoinIcon({ asset, icon = null, size = 28 }) {

  // Which logo failed to load, rather than a flag: a swap panel
  // keeps its instance when the direction flips, and the other
  // coin's logo must be tried afresh, not shown as a dot
  const [failedIcon, setFailedIcon] = useState(null)


  if (icon && icon !== failedIcon) {
    return (
      <img
        src={icon}
        alt=""
        onError={() => setFailedIcon(icon)}
        className="block flex-none object-contain"
        style={{ width: size, height: size }}
      />
    )
  }

  return (
    <span
      className="block flex-none rounded-full"
      style={{ width: size, height: size, backgroundColor: colorFromString(asset) }}
    />
  )
}
