// -----------------------------------------------------------
//  [*] App — route table
//
//  The root of the React app. Every page renders inside the
//  shared Exchange Layout (which owns the background and the
//  centered column), so this component is just the routes:
//
//    /                        — landing page
//    /exchange                — the swap form
//    /exchange/order/:orderId — live status of one order
//    /reserves                — payout wallets + balances
//
//  Anything else redirects home. The block explorer lives at
//  /explorer/ and is served by Caddy, outside React Router.
// -----------------------------------------------------------

import { Route, Routes, Navigate } from 'react-router-dom'

import Home from './pages/Home/Home.jsx'
import Exchange from './pages/Exchange/Exchange.jsx'
import Order from './pages/Exchange/Order.jsx'
import Reserves from './pages/Reserves/Reserves.jsx'







// -----------------------------------------------------------
// App (default export)
// -----------------------------------------------------------
//
// One route per page; any other path is replaced by home, so
// the mistyped URL leaves no entry in the history.
//
// Used by:
//   - main.jsx — mounted into #root inside BrowserRouter
// -----------------------------------------------------------

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />

      {/* Exchange */}
      <Route path="/exchange" element={<Exchange />} />
      <Route path="/exchange/order/:orderId" element={<Order />} />

      {/* Operator view */}
      <Route path="/reserves" element={<Reserves />} />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
