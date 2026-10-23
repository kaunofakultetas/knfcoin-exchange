// -----------------------------------------------------------
//  [*] Entry point — mounts the React app
//
//  Renders the App (the route table, see App.jsx) into the
//  #root div of index.html, inside StrictMode and the
//  BrowserRouter that owns the URL. Global styles (Tailwind)
//  are pulled in here.
// -----------------------------------------------------------

import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App.jsx'


createRoot(document.getElementById('root')).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
)
