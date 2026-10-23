############################################################
#  [*] Database tests — the schema and the connection helper
#
#  init_db against scratch SQLite files: every table with
#  every column the service and the worker write, a second run
#  that changes nothing, and the additive migration that gives
#  a database from before the payout-recovery, sweep and
#  refund work its new columns and table without losing a
#  row. get_db_connection
#  reads DB_PATH at every call (what lets each test point the
#  whole app at its own file), hands out rows readable by
#  column name, runs the file in write-ahead-logging mode — a
#  reader never held up by an open write — waits for a busy
#  database instead of failing at once, and closes every
#  connection when its with-block ends, the unit of work
#  committed or rolled back first.
############################################################


import os
import sqlite3
import tempfile
import time
import unittest

from app.database import get_db_connection, init_db


# Every column of the orders table, in the order init_db creates them
ORDER_COLUMNS = [
    'id', 'pair', 'from_asset', 'to_asset', 'from_amount', 'to_amount', 'rate', 'locked_rate', 'paid_coins',
    'destination', 'status', 'confirm_target', 'confirm_count', 'deposit_index', 'deposit_address',
    'deposit_scripthash', 'received_amount', 'tx_deposit_id', 'tx_send_id', 'tx_send_raw',
    'sweep_state', 'tx_sweep_id', 'error', 'created_at', 'updated_at', 'expires_at',
]

# Every column of the refunds table
REFUND_COLUMNS = ['txid', 'order_id', 'raw', 'coins', 'recipients', 'state', 'created_at', 'updated_at']

# The orders table as the first deployment created it
LEGACY_ORDERS = '''
    CREATE TABLE orders (
        id TEXT PRIMARY KEY, pair TEXT, from_asset TEXT NOT NULL, to_asset TEXT NOT NULL,
        from_amount REAL NOT NULL, to_amount REAL NOT NULL, rate REAL NOT NULL, locked_rate REAL,
        destination TEXT NOT NULL, status TEXT NOT NULL, confirm_target INTEGER NOT NULL DEFAULT 1,
        confirm_count INTEGER NOT NULL DEFAULT 0, deposit_index INTEGER, deposit_address TEXT,
        deposit_scripthash TEXT, received_amount REAL NOT NULL DEFAULT 0, tx_deposit_id TEXT,
        tx_send_id TEXT, error TEXT, created_at INTEGER NOT NULL, updated_at INTEGER NOT NULL,
        expires_at INTEGER
    )
'''








############################################################
# DatabaseTestCase
############################################################
#
# A scratch SQLite file per test, named by DB_PATH, and a
# table's column names as SQLite reports them.
#
# Used by:
#   - TestSchema, TestConnections (below)
############################################################

class DatabaseTestCase(unittest.TestCase):

    def setUp(self):
        self.path = self.scratch_file()
        os.environ['DB_PATH'] = self.path

    def tearDown(self):
        os.environ.pop('DB_PATH', None)

    def scratch_file(self):
        # The database and the write-ahead log's two side files
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        for name in (path, path + '-wal', path + '-shm'):
            self.addCleanup(lambda name=name: os.path.exists(name) and os.unlink(name))
        return path

    def columns(self, table):
        with get_db_connection() as conn:
            return [row['name'] for row in conn.execute(f'PRAGMA table_info({table})')]








############################################################
# TestSchema
############################################################
#
# init_db: every table with every column, a second run that
# changes nothing, and a database from the first deployment
# migrated without losing a row.
############################################################

class TestSchema(DatabaseTestCase):

    def test_creates_the_orders_table_with_every_column(self):
        init_db()
        self.assertEqual(self.columns('orders'), ORDER_COLUMNS)

    def test_creates_the_meta_key_value_table(self):
        init_db()
        self.assertEqual(self.columns('meta'), ['key', 'value'])

    def test_creates_the_refunds_table_read_by_order(self):
        init_db()
        self.assertEqual(self.columns('refunds'), REFUND_COLUMNS)
        with get_db_connection() as conn:
            indexes = [row['name'] for row in conn.execute('PRAGMA index_list(refunds)')]
        self.assertIn('refunds_by_order', indexes)

    def test_a_second_run_changes_nothing(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('next_deposit_index', '42')")
            conn.commit()

        init_db()

        self.assertEqual(self.columns('orders'), ORDER_COLUMNS)
        with get_db_connection() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'next_deposit_index'").fetchone()
        self.assertEqual(row['value'], '42')

    def test_an_older_database_gains_the_new_columns_and_keeps_its_rows(self):
        with get_db_connection() as conn:
            conn.execute(LEGACY_ORDERS)
            conn.execute(
                "INSERT INTO orders (id, from_asset, to_asset, from_amount, to_amount, rate, destination, status, created_at, updated_at) "
                "VALUES ('7F3A9C21', 'KNF Coin', 'LTC Testnet', 100, 12.345678, 0.12345678, 'tltc1qstudent', 'completed', 1, 2)"
            )
            conn.commit()

        init_db()

        self.assertEqual(sorted(self.columns('orders')), sorted(ORDER_COLUMNS))
        self.assertEqual(self.columns('refunds'), REFUND_COLUMNS)
        with get_db_connection() as conn:
            row = dict(conn.execute("SELECT * FROM orders WHERE id = '7F3A9C21'").fetchone())
        self.assertEqual(row['status'], 'completed')
        self.assertEqual(row['to_amount'], 12.345678)
        self.assertIsNone(row['tx_send_raw'])
        self.assertIsNone(row['sweep_state'])
        self.assertIsNone(row['paid_coins'])








############################################################
# TestConnections
############################################################
#
# get_db_connection: DB_PATH read at every call, rows read by
# column name, a busy database waited for, the file in
# write-ahead-logging mode, and every connection closed when
# its block ends.
############################################################

class TestConnections(DatabaseTestCase):

    def test_the_file_is_the_one_db_path_names_at_each_call(self):
        init_db()
        other = self.scratch_file()

        os.environ['DB_PATH'] = other
        with get_db_connection() as conn:
            tables = [row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]

        self.assertEqual(tables, [])

    def test_a_file_named_by_the_caller_wins_over_db_path(self):
        other = self.scratch_file()
        with get_db_connection(other) as conn:
            conn.execute('CREATE TABLE marker (x INTEGER)')
            conn.commit()

        self.assertEqual(self.columns('marker'), [])
        with get_db_connection(other) as conn:
            self.assertEqual([row['name'] for row in conn.execute('PRAGMA table_info(marker)')], ['x'])

    def test_rows_are_read_by_column_name(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
            row = conn.execute("SELECT * FROM meta WHERE key = 'k'").fetchone()

        self.assertEqual(dict(row), {'key': 'k', 'value': 'v'})

    def test_a_busy_database_is_waited_for_five_seconds(self):
        # The API threads and the worker thread write the same file
        with get_db_connection() as conn:
            self.assertEqual(conn.execute('PRAGMA busy_timeout').fetchone()[0], 5000)

    def test_every_connection_runs_in_write_ahead_logging_mode(self):
        with get_db_connection() as conn:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0], 'wal')

    def test_the_mode_sticks_to_the_file(self):
        # A plain connection — dbgate's, say — finds the file in WAL mode
        init_db()
        plain = sqlite3.connect(self.path)
        try:
            self.assertEqual(plain.execute('PRAGMA journal_mode').fetchone()[0], 'wal')
        finally:
            plain.close()

    def test_a_reader_is_not_held_up_by_an_open_write(self):
        # The worker writing an order never keeps a request from reading
        # orders — in the old rollback mode this read would wait out the
        # whole busy timeout and fail
        init_db()
        writer = sqlite3.connect(self.path, isolation_level=None)
        try:
            writer.execute('BEGIN EXCLUSIVE')
            writer.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
            started = time.monotonic()

            with get_db_connection() as reader:
                self.assertEqual(reader.execute('SELECT COUNT(*) FROM meta').fetchone()[0], 0)

            self.assertLess(time.monotonic() - started, 1)
        finally:
            writer.close()

    def test_a_connection_is_closed_when_its_block_ends(self):
        with get_db_connection() as conn:
            conn.execute('SELECT 1')

        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1')

    def test_a_block_that_ends_commits_its_work_first(self):
        init_db()
        with get_db_connection() as conn:
            conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")

        with get_db_connection() as conn:
            self.assertEqual(conn.execute("SELECT value FROM meta WHERE key = 'k'").fetchone()[0], 'v')

    def test_a_block_that_fails_rolls_back_and_still_closes(self):
        init_db()
        with self.assertRaises(RuntimeError):
            with get_db_connection() as conn:
                conn.execute("INSERT INTO meta (key, value) VALUES ('k', 'v')")
                raise RuntimeError('the unit of work failed')

        with self.assertRaises(sqlite3.ProgrammingError):
            conn.execute('SELECT 1')
        with get_db_connection() as check:
            self.assertEqual(check.execute('SELECT COUNT(*) FROM meta').fetchone()[0], 0)

    def test_once_every_connection_is_closed_no_side_file_is_left(self):
        # SQLite folds the write-ahead log back into the file and removes
        # both side files when the last connection closes
        init_db()
        self.assertFalse(os.path.exists(self.path + '-wal'))
        self.assertFalse(os.path.exists(self.path + '-shm'))
