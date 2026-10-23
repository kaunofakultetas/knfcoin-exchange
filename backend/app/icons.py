############################################################
#  [*] Coin icons
#
#  Serves the coin logos from the operator's mounted
#  configuration folder (CONFIG_DIR/icons — see
#  app/config.py). The file name IS the whole linkage: the
#  logo of the chain with network key <key> is the file
#  <key>.svg, <key>.png or <key>.webp in that folder.
#
#  Dropping a file into the mounted folder is enough — the
#  answers advertise it on their next read, no restart, no
#  rebuild, no config edit. A chain without a logo file is
#  advertised as null, and the frontend falls back to its
#  coloured dot.
#
#    GET /api/exchange/icons/<network> — the logo file itself
#
#  Used by:
#    - main.py — blueprint registration
#    - app/service.py — the rates, reserves and order answers
############################################################


import os

from flask import Blueprint, jsonify, send_from_directory

from . import config


bp_icons = Blueprint('icons', __name__)


# The folder the logos live in; its files are looked up at
# every request, so a dropped file needs no restart
ICONS_DIR = os.path.join(config.CONFIG_DIR, 'icons')

# Probed in this order — svg preferred, it stays crisp at the
# 24-40 px the pages draw a coin at
ICON_EXTENSIONS = ('svg', 'png', 'webp')








############################################################
# _icon_file
############################################################
#
# The logo file of one network key, as its name inside
# ICONS_DIR, or None when there is none. A key that could
# reach outside the folder (a path separator, "..") never
# names a file.
#
# Used by:
#   - icon_url, get_icon (below)
############################################################

def _icon_file(network):
    if not network or '/' in network or '\\' in network or '..' in network:
        return None

    for ext in ICON_EXTENSIONS:
        name = f'{network}.{ext}'
        if os.path.isfile(os.path.join(ICONS_DIR, name)):
            return name
    return None








############################################################
# icon_url
############################################################
#
# The URL an answer advertises for a chain's logo, or None
# when no logo file exists. The answers call it every time
# they are built, so a freshly dropped file shows up on the
# very next read. The URL carries no extension: the route
# below probes again, so replacing knf.png with knf.svg needs
# no other change.
#
# Used by:
#   - app/service.py — rates_snapshot, reserves_snapshot and
#     every order answer
############################################################

def icon_url(network):
    if _icon_file(network) is None:
        return None
    return f'/api/exchange/icons/{network}'








############################################################
# get_icon
############################################################
#
# GET /api/exchange/icons/<network>
#
# The logo file itself, cached by the browser for an hour —
# short enough that a replaced logo shows within the hour. A
# network without a logo file is a 404 carrying the same
# {"error": ...} body as every other failure of the API.
#
# Used by:
#   - CoinIcon.jsx — the image it shows wherever an answer
#     advertised a logo URL
############################################################

@bp_icons.route('/api/exchange/icons/<network>', methods=['GET'])
def get_icon(network):
    name = _icon_file(network)
    if name is None:
        return jsonify({'error': 'Not found'}), 404

    return send_from_directory(ICONS_DIR, name, max_age=3600)
