# Backend tests

The unittest suite of the exchange backend: the service, the order
worker, the wallet, the HTTP API and the app's wiring — offline, on
FakeWallets and scratch SQLite files, with no Electrum server, node, seed
or network anywhere.

| Layer | Files | Needs network? | When to run |
|---|---|---|---|
| Offline regression | `test_service.py`, `test_worker.py`, `test_wallet.py`, `test_reorg.py`, `test_lifecycle.py`, `test_refunds.py`, `test_reserve_shortfall.py`, `test_several_deposits.py`, `test_routes.py`, `test_icons.py`, `test_chains.py`, `test_database.py`, `test_config.py`, `test_app.py` | no | always |
| API contract | `test_api_contract.py`, with `contract.py` | no | always |
| Live smoke | `integration/test_live_smoke.py` | yes (the running backend) | opt-in via `RUN_LIVE=1` |

## Running

```sh
./runTests.sh                         # the whole offline suite, in a throwaway container
./runTests.sh tests.test_reorg        # one module, class or test
./runTests.sh -k vanished             # the tests whose name matches
```

`runTests.sh` builds the production image under a tag of its own
(`knfexchange-backend-check`) and runs the suite in a container with no
network and no seed, so no test can reach a chain or touch real funds.
The repository's `_CONFIG` folder is mounted read-only at `/config`, where
the app reads its chains (`coins.py`) and the coin logos, so
`test_chains.py` and `test_icons.py` check the configuration that ships;
every other test runs on chains and a logo folder of its own.
The live smoke layer needs the running backend; inside its container:

```sh
sudo docker exec -w /app -e RUN_LIVE=1 knfexchange-backend python -m unittest discover -t . -s tests -v
```

## The contract with the frontend

The SPA (`vite/app`) reads the API field by field: amounts as whole
coins, times as epoch milliseconds, the status strings and asset labels
it knows, the `error` sentence of a failed answer. `contract.py` is the
backend's written copy of what it reads, and `test_api_contract.py`
holds the Flask app's real answers to it — an order at every stage of its
life, the new order the swap form opens, the rates, the reserves, every
failed answer. The live smoke layer holds the running backend's answers
to the same contract.

The frontend's suite keeps its own copy in its test double (and checks
that the double answers every field the SPA reads). The two suites share
no file on purpose: a change to an answer the pages read is made on both
sides — `contract.py` here, the double there.

## Conventions

- Offline by default: a test that talks to the network belongs under
  `integration/` and skips itself unless `RUN_LIVE=1` is set.
- FakeWallet stands in for the wallet everywhere but `test_wallet.py`;
  its `receive`, `mine`, `orphan` and `drop` script a chain the way a
  reorganisation moves it, `bury` confirms a payout or refund it
  broadcast, and `tick()` runs one pass of the real worker loop. Its
  reserve covers any order (`reserve_balance`, lower it to refuse one),
  and every deposit transaction has a sender a refund goes back to,
  named after it (`senders` names another, `None` none at all, an
  exception a server that does not hand the transaction out). An order completes
  only once its payout has confirmed, so a test that wants a completed
  order buries the payout and runs the payout step again.
- `CoinWallet` is a FakeWallet whose payouts, sweeps and refunds move
  the coins they spend: a payout is paid from the reserve's coins
  (picked, and refused when short, the way the real wallet does it), a
  sweep carries a deposit into the reserve, a refund sends coins back to
  their senders, and `payouts` and `refunds` record what the students
  were really paid and sent back; its reserve can spend what is on it. A test class gets it by setting
  `wallet_class = CoinWallet` — for orders that share a reserve, run it
  short or are paid more than once. Its `lagging` view sees a broadcast
  only at `catch_up()`, the way an Electrum server sees it only at its
  next mempool refresh.
- A defect a test finds is not fixed from here: the test states the
  wanted behaviour and is decorated `@known_bug('…')` — an expected
  failure that prints the bug under its name. Once the fix lands,
  unittest reports an "unexpected success", which fails the run: the cue
  to drop the decorator.
- Style: test files carry the house file and class banners (eight blank
  lines before each class), but test methods use single blank lines and,
  where the name needs it, a one-line comment instead of full method
  banners — a test's name is its documentation, a sentence about
  behaviour. The helper modules (`base.py`, `fakes.py`, `contract.py`)
  banner their classes and functions the same way.
