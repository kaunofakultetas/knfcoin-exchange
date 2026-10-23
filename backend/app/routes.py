############################################################
#  [*] Exchange HTTP API
#
#  The REST surface consumed by the React frontend, mounted
#  at /api/exchange/* (proxied same-origin through Caddy, so
#  no CORS handling is needed):
#
#    GET  /api/exchange/health        — liveness probe
#    GET  /api/exchange/rates         — live rates + limits
#    GET  /api/exchange/reserves      — payout wallets + balances
#    GET  /api/exchange/orders        — latest orders
#    POST /api/exchange/orders        — create an order
#    GET  /api/exchange/orders/<id>   — one order's state
#
#  A deliberately thin layer: it validates nothing itself,
#  just calls the ExchangeService and maps its exceptions
#  onto the right status codes (ValidationError -> 400,
#  Unavailable -> 503, anything else -> 500) — every failure
#  answered as JSON {"error": ...}, the field the frontend
#  shows its sentence from.
#
#  The service instance is created by create_app() and stored
#  in app.extensions — no module-level globals, so tests can
#  build isolated apps side by side.
#
#  Used by:
#    - main.py — blueprint registration
############################################################


import logging

from flask import Blueprint, request, jsonify, current_app
from werkzeug.exceptions import HTTPException

from .service import Unavailable, ValidationError


logger = logging.getLogger('exchange.api')


bp_exchange = Blueprint('exchange', __name__)








############################################################
# _service
############################################################
#
# The ExchangeService of the app serving the request, as
# create_app() stored it in app.extensions.
#
# Used by:
#   - every route below
############################################################

def _service():
    return current_app.extensions['exchange_service']








############################################################
# api_health
############################################################
#
# GET /api/exchange/health
#
# Liveness probe: answers as soon as the app is up, without
# touching the database or Electrum.
#
# Used by:
#   - nothing in the stack polls it at the moment
############################################################

@bp_exchange.route('/api/exchange/health', methods=['GET'])
def api_health():
    return jsonify({'status': 'ok'})








############################################################
# api_rates
############################################################
#
# GET /api/exchange/rates
#
# Live rates + the amount limits the backend enforces, so the
# UI and the server always agree on the numbers.
#
# Used by:
#   - Exchange.jsx — useLiveRates, the swap form's quote and
#     limits
#   - Home.jsx — LiveRateChip
############################################################

@bp_exchange.route('/api/exchange/rates', methods=['GET'])
def api_rates():
    return jsonify(_service().rates_snapshot())








############################################################
# api_reserves
############################################################
#
# GET /api/exchange/reserves
#
# Reserve (payout) wallet of every chain with its live
# balance, so an operator can see on the GUI which wallet
# needs a top-up.
#
# Used by:
#   - Reserves.jsx — the reserves page and its refresh
############################################################

@bp_exchange.route('/api/exchange/reserves', methods=['GET'])
def api_reserves():
    return jsonify(_service().reserves_snapshot())








############################################################
# api_list_orders
############################################################
#
# GET /api/exchange/orders
#
# The latest orders, newest first. Garbage or extreme
# ?limit= values fall back to sane bounds (20 by default, 1
# to 100) instead of turning into a 500.
#
# Used by:
#   - Exchange.jsx — useRecentOrders, the list under the form
############################################################

@bp_exchange.route('/api/exchange/orders', methods=['GET'])
def api_list_orders():
    try:
        limit = int(request.args.get('limit', 20))
    except ValueError:
        limit = 20

    return jsonify(_service().list_orders(max(1, min(limit, 100))))








############################################################
# api_create_order
############################################################
#
# POST /api/exchange/orders
#
# Creates an order from the swap form's request and answers
# it with 201. A refusal the student can fix (a bad amount,
# a bad address, more than the reserve can pay out, ...) is a
# 400 carrying the service's own sentence, and a reserve that
# cannot be read right now a 503 carrying its own; anything
# unexpected is a 500 with a generic one, the cause logged.
#
# Used by:
#   - Exchange.jsx — SwapForm, on submit
############################################################

@bp_exchange.route('/api/exchange/orders', methods=['POST'])
def api_create_order():
    try:
        order = _service().create_order(request.get_json(silent=True) or {})
        return jsonify(order), 201

    except ValidationError as e:
        # Something the student can fix (bad amount, bad address, ...).
        return jsonify({'error': str(e)}), 400

    except Unavailable as e:
        # The exchange's side: the order is not taken until it can be checked.
        return jsonify({'error': str(e)}), 503

    except Exception as e:
        # Unexpected server-side failure.
        logger.error('Unexpected error creating order: %s', e)
        return jsonify({'error': 'Internal error creating order'}), 500








############################################################
# api_get_order
############################################################
#
# GET /api/exchange/orders/<order_id>
#
# One order's current state, or a 404 for an id the
# database does not know.
#
# Used by:
#   - Order.jsx — the order page, polled every 2 seconds
############################################################

@bp_exchange.route('/api/exchange/orders/<order_id>', methods=['GET'])
def api_get_order(order_id):
    order = _service().get_order(order_id)
    if not order:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(order)








############################################################
# api_unexpected_error
############################################################
#
# Anything a route did not foresee (the database locked, an
# Electrum query raising) answers like every other failure: a
# 500 carrying {"error": ...} - never Flask's HTML error page,
# whose missing sentence would leave the frontend only the
# bare status to show. HTTP errors Flask raises itself keep
# their own answer.
#
# Used by:
#   - Flask — any exception a route of this blueprint raises
############################################################

@bp_exchange.errorhandler(Exception)
def api_unexpected_error(error):
    if isinstance(error, HTTPException):
        return error

    logger.error('Unexpected error on %s %s: %s', request.method, request.path, error)
    return jsonify({'error': 'Internal server error'}), 500
