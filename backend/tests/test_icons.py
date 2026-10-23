############################################################
#  [*] Icon tests — the coin logos
#
#  app/icons.py against scratch logo folders: the URL an
#  answer advertises for a chain — only while its logo file
#  exists, whatever image type it is, picked up the moment
#  the file is dropped — and the route that serves the files:
#  the right content type, an hour of browser cache, svg
#  before png, a 404 in the API's own words for a chain
#  without a logo, and nothing outside the folder, whatever
#  the request names. Last, the logos the repository ships in
#  _CONFIG/icons: one for every chain the exchange trades.
############################################################


import os
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from unittest.mock import patch

from flask import Flask

from app import config
from app.chains import CHAINS
from app.icons import ICON_EXTENSIONS, bp_icons, icon_url


# A minimal logo in each image type the folder may hold
LOGOS = {
    'svg': b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><circle cx="16" cy="16" r="16"/></svg>',
    'png': b'\x89PNG\r\n\x1a\n' + b'\x00' * 16,
    'webp': b'RIFF\x10\x00\x00\x00WEBPVP8 ' + b'\x00' * 8,
}








############################################################
# IconFolderTestCase
############################################################
#
# A scratch logo folder per test, patched in as the folder
# app/icons.py reads, and a way to drop a logo into it.
#
# Used by:
#   - TestIconUrl, TestServingIcons (below)
############################################################

class IconFolderTestCase(unittest.TestCase):

    def setUp(self):
        self.icons_dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.icons_dir)
        folder = patch('app.icons.ICONS_DIR', self.icons_dir)
        folder.start()
        self.addCleanup(folder.stop)

    def drop(self, name, content=None):
        # A logo file the operator puts into the mounted folder
        content = content if content is not None else LOGOS[name.rsplit('.', 1)[1]]
        with open(os.path.join(self.icons_dir, name), 'wb') as logo:
            logo.write(content)








############################################################
# TestIconUrl
############################################################
#
# The URL the answers advertise: present exactly while the
# chain has a logo file, and never for a name that could
# reach outside the folder.
############################################################

class TestIconUrl(IconFolderTestCase):

    def test_a_chain_with_a_logo_is_advertised_at_its_icon_route(self):
        self.drop('knf.svg')
        self.assertEqual(icon_url('knf'), '/api/exchange/icons/knf')

    def test_every_image_type_the_folder_may_hold_counts(self):
        for ext in ICON_EXTENSIONS:
            with self.subTest(ext=ext):
                self.drop(f'ltc4.{ext}')
                self.assertEqual(icon_url('ltc4'), '/api/exchange/icons/ltc4')
                os.unlink(os.path.join(self.icons_dir, f'ltc4.{ext}'))

    def test_a_chain_without_a_logo_is_advertised_as_null(self):
        self.drop('knf.svg')
        self.assertIsNone(icon_url('ltc4'))

    def test_another_file_type_is_no_logo(self):
        self.drop('knf.gif', b'GIF89a')
        self.assertIsNone(icon_url('knf'))

    def test_a_logo_dropped_later_is_advertised_at_the_next_read(self):
        self.assertIsNone(icon_url('knf'))
        self.drop('knf.svg')
        self.assertEqual(icon_url('knf'), '/api/exchange/icons/knf')

    def test_a_name_that_could_leave_the_folder_names_no_logo(self):
        self.drop('knf.svg')
        os.makedirs(os.path.join(self.icons_dir, 'sub'))
        self.drop(os.path.join('sub', 'knf.svg'))
        for network in ('../icons/knf', 'sub/knf', 'sub\\knf', '..', '', None):
            with self.subTest(network=network):
                self.assertIsNone(icon_url(network))








############################################################
# TestServingIcons
############################################################
#
# GET /api/exchange/icons/<network> through the blueprint on
# its own: the file with its content type and cache, or the
# API's 404.
############################################################

class TestServingIcons(IconFolderTestCase):

    def setUp(self):
        super().setUp()
        app = Flask(__name__)
        app.register_blueprint(bp_icons)
        self.client = app.test_client()

    def get(self, network):
        response = self.client.get(f'/api/exchange/icons/{network}')
        self.addCleanup(response.close)
        return response

    def test_a_logo_is_served_as_it_lies_in_the_folder(self):
        self.drop('knf.svg')

        response = self.get('knf')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'image/svg+xml')
        self.assertEqual(response.get_data(), LOGOS['svg'])

    def test_the_browser_keeps_a_logo_for_an_hour(self):
        self.drop('knf.svg')
        self.assertEqual(self.get('knf').cache_control.max_age, 3600)

    def test_a_png_logo_is_served_as_a_png(self):
        self.drop('ltc4.png')

        response = self.get('ltc4')

        self.assertEqual(response.mimetype, 'image/png')
        self.assertEqual(response.get_data(), LOGOS['png'])

    def test_an_svg_is_preferred_over_a_png_of_the_same_chain(self):
        self.drop('knf.png')
        self.drop('knf.svg')
        self.assertEqual(self.get('knf').mimetype, 'image/svg+xml')

    def test_a_replaced_logo_is_served_under_the_same_url(self):
        self.drop('knf.png')
        self.assertEqual(self.get('knf').mimetype, 'image/png')

        os.unlink(os.path.join(self.icons_dir, 'knf.png'))
        self.drop('knf.svg')

        self.assertEqual(self.get('knf').mimetype, 'image/svg+xml')

    def test_a_chain_without_a_logo_is_the_apis_404(self):
        response = self.get('dogecoin')

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json(), {'error': 'Not found'})

    def test_nothing_outside_the_folder_is_served(self):
        # A file beside the folder that a request must never reach
        with open(os.path.join(os.path.dirname(self.icons_dir), 'secret.svg'), 'wb') as secret:
            secret.write(LOGOS['svg'])
        self.addCleanup(os.unlink, os.path.join(os.path.dirname(self.icons_dir), 'secret.svg'))

        for path in ('..%2Fsecret', '..', '%2E%2E%2Fsecret', '..\\secret'):
            with self.subTest(path=path):
                self.assertEqual(self.get(path).status_code, 404)








############################################################
# TestShippedLogos
############################################################
#
# The logos the repository ships in _CONFIG/icons, read
# where the app reads them (CONFIG_DIR — runTests.sh mounts
# the folder there): every chain the exchange trades has one,
# and each is an image a browser can draw.
############################################################

class TestShippedLogos(unittest.TestCase):

    def logo_of(self, network):
        folder = os.path.join(config.CONFIG_DIR, 'icons')
        found = [os.path.join(folder, f'{network}.{ext}') for ext in ICON_EXTENSIONS
                 if os.path.isfile(os.path.join(folder, f'{network}.{ext}'))]
        return found[0] if found else None

    def test_every_chain_has_its_logo(self):
        for network in CHAINS:
            with self.subTest(network=network):
                self.assertIsNotNone(self.logo_of(network), f'no logo for {network} in {config.CONFIG_DIR}/icons')

    def test_every_svg_logo_is_a_well_formed_svg_without_scripts(self):
        # Served from the exchange's own origin, a logo must never carry
        # anything that runs
        for network in CHAINS:
            path = self.logo_of(network)
            if not path or not path.endswith('.svg'):
                continue
            with self.subTest(network=network):
                root = ElementTree.parse(path).getroot()
                self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
                tags = {element.tag.split('}')[-1] for element in root.iter()}
                attributes = {name.lower() for element in root.iter() for name in element.attrib}
                self.assertNotIn('script', tags)
                self.assertNotIn('foreignObject', tags)
                self.assertEqual([name for name in attributes if name.startswith('on')], [])
