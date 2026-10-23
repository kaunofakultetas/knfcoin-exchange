# Frontend tests

The vitest suite of the KNF Exchange SPA: every page, component and the
API client rendered or called in jsdom against a fake backend (msw), with
no real backend, Electrum server, browser or network anywhere.

## Running

```sh
../runTests.sh                      # the whole suite, in a throwaway container
../runTests.sh tests/pages          # a folder, a file, or -t "test name"
../runTests.sh --coverage           # with a coverage report
```

`runTests.sh` builds the builder stage of the production Dockerfile
(so `npm run build` must pass first) and runs vitest in it — the host
needs no node. While developing, the running dev container is quicker:

```sh
sudo docker exec -it -w /app -e TMPDIR=/app/node_modules/.tmp knfexchange-vite npx vitest run tests/pages/reserves.test.jsx
```

(its root filesystem is read-only, so vitest's temp files go under
`node_modules/.tmp` — on disk, ignored by git and docker; not `/dev/shm`,
whose 64 MB fill up after a few dozen runs). `npx eslint tests` lints
the suite like the app.

## Layout

| Folder | What lives there |
|---|---|
| `support/` | The harness: `setup.js` (the backend double's lifecycle, the per-test slate, the console and unhandled-request guards), `render.jsx` (`renderPage`, `renderApp`), `location.js`, `regions.js` (finding the parts of a page that have no landmark), `backend/` (the msw server with `given.*`, the default `handlers.js`, `fixtures.js`, the `contract.js` matrix), `shell/` (the route table read from `App.jsx`, request watchers, router helpers) and the handles on the two big pages (`exchange/`, `order/`) |
| `core/` | The app as a whole: the harness smoke test, structural rules (every backend call has a handler …), App routing, navigation and history, StrictMode |
| `components/` | The shared components of `pages/Exchange/components`: Header, Layout, Footer, CoinIcon, CopyableAddress, StatusBadge |
| `lib/` | `pages/Exchange/lib`: the ExchangeApi client and the order statuses |
| `pages/` | One file per page (a folder for the big ones), behaviour plus the backend contract of every endpoint the page reads |
| `contract/` | The route sweep: every route under every backend failure mode |

## Rules

- **Nothing real.** Every request goes to the msw double. A request no
  handler answers fails the test — add a default handler in
  `support/backend/handlers.js` (a new endpoint in `src/`) or answer it
  in the test with `given.*`. `core/structural.test.js` checks every
  call in `src/` has a default handler.
- **Every field the SPA reads is in the double.** `core/structural.test.js`
  reads, from `src/`, the fields ExchangeApi takes off an order and a
  reserve, and the rate keys and limits the pages look up, and checks the
  double answers all of them in the units the pages compute with
  (amounts as numbers of whole coins, times as epoch milliseconds). The
  backend's suite keeps its own copy of the same contract and holds the
  real answers to it (`backend/tests/contract.py`,
  `test_api_contract.py`). The two suites share no file on purpose: a
  change to an answer the pages read is made on both sides.
- **Declare only the deviation.** Default handlers answer the happy
  path from `fixtures.js`, and behave like the backend where a page
  depends on it (the order list's `?limit=`, the 404 of an unknown
  order, every refusal of a new order in `create_order`'s own words); a
  test overrides one endpoint with `given.json / error / html / text /
  empty / networkError / hang / slow / capture / sequence`. Fixtures are
  shared: copy and edit (`{ ...f.orderById(id), status: 'refunded' }`),
  never mutate them — the builders hand out fresh copies.
- **Globals through `vi.stubGlobal`.** Timers, environment variables,
  stubbed globals and spies are all undone after each test by
  `setup.js`.
- **No bug fixed from here.** A test that finds a defect in `src/` does
  not change `src/`: it pins the defect with `it.fails` (the contract
  matrix's `pins`) and a one-line description, so the suite stays green
  while the bug is on record. The file header of every file holding a
  pin says what is pinned.
- **Assert what a student sees.** Roles, labels and the texts verbatim;
  no snapshots, no class names, no implementation internals unless the
  behaviour lives there (the ring of the highlighted pill, a progress
  bar's width and colour, a countdown turning amber).
- **Console discipline.** React's bug reports (a missing key, a hook
  order change …) and jsdom's refusal of a hard navigation fail the
  test; a test that provokes one on purpose declares it with
  `allowConsoleErrors(/…/)`.

## Practical notes

What the suite learned the hard way:

- **Polling pages.** The Order page polls every 2 s (and ticks its
  countdown every second), Reserves every 10 s, the swap form's rates
  every 15 s; the recent orders' ages are worded anew every 30 s
  without a request. A test that drives a poll fakes the intervals only —
  `vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })`, plus
  `'Date'` for the countdown — so everything else, the answers on their
  way through msw included, runs on real time. With `setInterval`
  faked, `waitFor` re-checks only on DOM changes: to wait for a request
  that changes nothing on screen, `settle()`.
- **Register the watcher last.** `watchRequests()` lets every request
  fall through to the handler that answers it — but only to handlers
  registered before it. Call `given.*` first, then the watcher.
- **Numbers and dates.** The pages format amounts with the runtime's
  default locale — en-US in the container, so `1,234.5` — and creation
  times in local time: `vi.stubEnv('TZ', 'Europe/Vilnius')`, undone
  after every test by `setup.js`.
- **Clipboard.** `userEvent.setup()` (inside `renderPage` / `renderApp`)
  installs its own clipboard on `navigator`; spy on
  `navigator.clipboard.writeText` rather than stubbing the global.
- **Plain links.** The explorer links (`/explorer/`, served by Caddy)
  are plain `<a>`s; clicking one for real makes jsdom log "Not
  implemented: navigation", which fails the test. Ask
  `followedByTheBrowser(link)` instead — it cancels the navigation after
  reading whether the router took the click. jsdom reports that refusal
  a task later and on its own console, which `setup.js` listens to.
- **Accessible names.** The home page's headline puts a space at the
  start of an inner `<span>`, which the accessible-name computation
  drops ("byactually"); match such a heading by what it reads with
  `name: wholeText('…')`.
- **One missing-key report per file.** React reports a missing `key`
  once per parent element type for the life of the module — once per
  test file. A pin that relies on that report must be the first of its
  kind in its file. The huge-list variant repeats entries with equal
  keys, so React's "two children with the same key" warning there is
  expected — and deliberately not fatal.
- **StrictMode.** `renderApp` leaves StrictMode out so a test can count
  requests; `core/app.test.jsx` mounts the App under it the way
  `main.jsx` does, where every effect runs twice.

## Style

The house style of the app: a file header banner saying what the file
covers, a banner per `describe` group, seven blank lines between
sections, two between tests; test names are sentences about behaviour
("shows the backend's refusal word for word"), not method names.
