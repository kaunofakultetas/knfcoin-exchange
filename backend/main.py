############################################################
#  [*] KNF Coin exchange backend — entry point
#
#  Boots the Flask app: validates the configuration, prepares
#  the SQLite database, builds the exchange service (wallets +
#  the order worker that watches deposits, sends payouts and
#  sweeps finished deposits back into the reserves over
#  Electrum) and exposes the HTTP API under /api/exchange/*.
#
#  Module layout:
#    app/config.py   — environment knobs + validation
#    app/chains.py   — the chains, loaded from _CONFIG/coins.py
#    app/coins.py    — the protocol facts of each coin
#    app/database.py — SQLite connection + schema
#    app/wallet.py   — per-chain HD wallet over Electrum
#    app/electrum_client.py
#                    — the connection to one Electrum server
#    app/service.py  — validation, pricing, order CRUD
#    app/worker.py   — the order lifecycle state machine
#    app/routes.py   — the REST API consumed by the frontend
#    app/icons.py    — the coin logos the frontend shows
#
#  Used by:
#    - Dockerfile — the container runs this file directly
#    - tests/test_app.py — the wiring of create_app
############################################################


import logging

from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from app import config








############################################################
# Logging
############################################################
#
# Timestamped, levelled logs for every exchange module
# (exchange.service / exchange.worker / exchange.electrum /
# exchange.api). Incident debugging lives or dies on knowing
# WHEN the worker saw a deposit, so plain print() is not
# enough here.
############################################################

logging.basicConfig(
    level=config.LOG_LEVEL,
    format='%(asctime)s %(levelname)-7s %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)








############################################################
# create_app
############################################################
#
# Flask application factory, kept tiny on purpose: fail fast
# on bad configuration, make sure the database schema exists,
# build the exchange service (wallets + order worker) and
# mount its HTTP routes. The service instance lives in
# app.extensions so request handlers reach it through
# current_app — no module globals.
#
# All requests reach us same-origin through the Caddy
# endpoint, so no CORS handling is needed.
#
# Used by:
#   - the entrypoint below
#   - tests/test_app.py — the app as the container starts it
############################################################

def create_app():
    # STEP 1: fail fast on a bad configuration — the
    # environment knobs and the mounted coins file
    # ==============================================
    config.validate()


    # STEP 2: the database schema (idempotent)
    # ========================================
    from app.database import init_db
    init_db()


    # STEP 3: the Flask app
    # =====================
    app = Flask(__name__)


    # STEP 4: trust the X-Forwarded-* headers of the reverse
    # proxy in front, so the client's real address is seen
    # ======================================================
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)


    # STEP 5: the exchange service — its wallets and the
    # order worker thread, started here
    # ==================================================
    from app.chains import CHAINS
    from app.service import ExchangeService
    service = ExchangeService(CHAINS)
    service.log_reserve_addresses()
    service.start_worker()
    app.extensions['exchange_service'] = service


    # STEP 6: the HTTP API the frontend talks to, and the coin
    # logos its pages show
    # ========================================================
    from app.routes import bp_exchange
    from app.icons import bp_icons
    app.register_blueprint(bp_exchange)
    app.register_blueprint(bp_icons)


    return app








############################################################
# Entrypoint
############################################################
#
# The server, when the file is run directly — which is how
# the container starts it.
############################################################

if __name__ == '__main__':

    app = create_app()

    # use_reloader stays off even in debug mode: the reloader would spawn a
    # second process and therefore a second worker thread, and two workers
    # polling the same Electrum servers would race on the same orders.
    app.run(host='0.0.0.0', port=8000, debug=config.APP_DEBUG, use_reloader=False)
