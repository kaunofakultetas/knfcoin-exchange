############################################################
#  [*] Exchange database
#
#  The whole persistence layer: an SQLite connection helper
#  and the schema. Three tables are all the exchange needs:
#
#    orders  — one row per swap, mutated by the worker as the
#              order walks through its lifecycle
#    refunds — one row per transaction sending an order's
#              coins back to the addresses they came from
#    meta    — tiny key/value store (currently just the next
#              HD child index for deposit addresses)
#
#  The file lives at DB_PATH (default /data/exchange.db) so
#  docker-compose can mount it under ./_DATA on the host. It
#  runs in write-ahead-logging mode, whose two side files
#  (exchange.db-wal and exchange.db-shm) live beside it — so
#  whatever else opens the database, dbgate included, must
#  mount the whole folder, never the file alone.
#
#  Used by:
#    - main.py        — init_db() before the app starts
#    - app/service.py — get_db_connection() for every query
#    - app/worker.py  — the same, from the worker thread
############################################################


import os
import sqlite3








############################################################
# ClosingConnection
############################################################
#
# sqlite3's own with-block commits or rolls back its unit of
# work but leaves the connection OPEN until the garbage
# collector gets to it — newer Pythons report every one of
# those as an unclosed database. Every caller in the app holds
# a connection for exactly one with-block, so here the end of
# the block closes it too.
#
# Used by:
#   - get_db_connection (below) — every connection it opens
############################################################

class ClosingConnection(sqlite3.Connection):






    ############################################################
    # __exit__
    ############################################################
    #
    # Commits or rolls back exactly as sqlite3 does, then
    # closes — in a finally, so a failing commit still releases
    # the handle.
    #
    # Used by:
    #   - every with-block holding a get_db_connection()
    #     connection
    ############################################################

    def __exit__(self, exc_type, exc_value, traceback):
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()








############################################################
# get_db_connection
############################################################
#
# Opens the exchange database. row_factory = sqlite3.Row lets
# callers read columns by name and turn a row straight into a
# dict with dict(row), which the service layer relies on.
#
# DB_PATH is read at CALL time (not import time) so tests can
# point the whole app at a scratch database just by setting
# the environment variable.
#
# Two threads write to this file (Flask request handlers and
# the order worker), and dbgate reads it from its own
# container. Write-ahead logging lets readers and the writer
# pass each other — a reader is never blocked by an open
# write, nor the writer by a reader — and busy_timeout makes
# one writer wait for the other's lock instead of instantly
# failing with "database is locked".
#
# Callers hold the connection in a with-block, which commits
# (or rolls back) their unit of work and then closes the
# connection (ClosingConnection above).
#
# Used by:
#   - app/service.py — every query
#   - app/worker.py  — the same, from the worker thread
#   - init_db (below)
############################################################

def get_db_connection(filename=None):
    conn = sqlite3.connect(filename or os.getenv('DB_PATH', '/data/exchange.db'), factory=ClosingConnection)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout = 5000')
    # A property of the file once set; a no-op on every later connection
    conn.execute('PRAGMA journal_mode = WAL')
    return conn








############################################################
# init_db
############################################################
#
# Creates the schema on first boot. CREATE TABLE IF NOT EXISTS
# makes it a no-op on every boot after that.
#
# orders columns worth explaining:
#
#   deposit_address / deposit_scripthash
#       the unique, per-order address the student must pay
#       into and the Electrum scripthash used to watch it
#   deposit_index
#       the HD child index the address was derived at
#   confirm_target / confirm_count
#       required vs currently-seen confirmations of the deposit
#   received_amount
#       what actually arrived (the payout is based on this)
#   tx_deposit_id / tx_send_id
#       the incoming deposit tx and the outgoing payout tx
#   tx_send_raw
#       the signed payout transaction, persisted BEFORE it is
#       broadcast: after a crash the worker rebroadcasts this
#       exact transaction (same txid) instead of building a
#       new one, which makes a double payout impossible
#   locked_rate
#       the rate actually paid out, frozen the moment the
#       deposit confirms (rate is just the quote at creation)
#   paid_coins
#       the coins on the deposit address the payout pays for,
#       fixed with the rate (a JSON list of "txid:vout"): a
#       coin that arrives later is not exchanged but sent back,
#       and only these are swept. NULL before the rate lock,
#       again once the order's coins are sent back instead, and
#       on orders locked before the column existed
#   sweep_state / tx_sweep_id
#       after the order finishes, the deposited coins are swept
#       from the per-order address into the chain's reserve so
#       payouts stay funded; NULL = not swept yet, 'swept' =
#       done (tx_sweep_id holds the sweep tx), 'dust' = the
#       leftover was too small to be worth a transaction,
#       'missing' = the deposit left the chain after the payout
#       (reorganised away or double-spent) - nothing to sweep
#   error
#       last payout failure, kept so the order can retry — or
#       why an order failed, or why its coins were sent back
#
# refunds columns:
#
#   txid / raw
#       the signed refund, persisted BEFORE it is broadcast,
#       like a payout: after a crash the very same refund goes
#       out again, never a second one
#   coins
#       the outpoints it spends ("txid:vout", JSON), never
#       refunded twice while the row exists
#   recipients
#       who is paid what: a JSON list of {address, amount}, the
#       amount in whole coins, the address null for a script
#       the exchange cannot name
#   state
#       'pending' until it is as deep as a deposit must be,
#       then 'confirmed'; a refund the chain refused for good
#       is deleted, its coins free to be sent back again
#
# Used by:
#   - main.py — called from create_app()
############################################################

def init_db():
    with get_db_connection() as conn:


        # STEP 1: the orders table, one row per swap
        # ==========================================
        conn.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id                  TEXT    PRIMARY KEY,
                pair                TEXT,
                from_asset          TEXT    NOT NULL,
                to_asset            TEXT    NOT NULL,
                from_amount         REAL    NOT NULL,
                to_amount           REAL    NOT NULL,
                rate                REAL    NOT NULL,
                locked_rate         REAL,
                paid_coins          TEXT,
                destination         TEXT    NOT NULL,
                status              TEXT    NOT NULL,
                confirm_target      INTEGER NOT NULL DEFAULT 1,
                confirm_count       INTEGER NOT NULL DEFAULT 0,
                deposit_index       INTEGER,
                deposit_address     TEXT,
                deposit_scripthash  TEXT,
                received_amount     REAL    NOT NULL DEFAULT 0,
                tx_deposit_id       TEXT,
                tx_send_id          TEXT,
                tx_send_raw         TEXT,
                sweep_state         TEXT,
                tx_sweep_id         TEXT,
                error               TEXT,
                created_at          INTEGER NOT NULL,
                updated_at          INTEGER NOT NULL,
                expires_at          INTEGER
            )
        ''')


        # STEP 2: the refunds table, one row per refund
        # transaction, read by the order it belongs to
        # =============================================
        conn.execute('''
            CREATE TABLE IF NOT EXISTS refunds (
                txid        TEXT    PRIMARY KEY,
                order_id    TEXT    NOT NULL,
                raw         TEXT    NOT NULL,
                coins       TEXT    NOT NULL,
                recipients  TEXT    NOT NULL,
                state       TEXT    NOT NULL,
                created_at  INTEGER NOT NULL,
                updated_at  INTEGER NOT NULL
            )
        ''')
        conn.execute('CREATE INDEX IF NOT EXISTS refunds_by_order ON refunds (order_id)')


        # STEP 3: the meta key/value table
        # ================================
        conn.execute('''
            CREATE TABLE IF NOT EXISTS meta (
                key    TEXT PRIMARY KEY,
                value  TEXT
            )
        ''')


        # STEP 4: additive migration — CREATE TABLE IF NOT EXISTS
        # never alters an existing table, so columns added after
        # the first deployment are bolted on here (a no-op on
        # freshly created databases)
        # =======================================================
        existing = {row['name'] for row in conn.execute('PRAGMA table_info(orders)')}
        for column, col_type in [('tx_send_raw', 'TEXT'), ('sweep_state', 'TEXT'), ('tx_sweep_id', 'TEXT'),
                                 ('paid_coins', 'TEXT')]:
            if column not in existing:
                conn.execute(f'ALTER TABLE orders ADD COLUMN {column} {col_type}')

        conn.commit()
