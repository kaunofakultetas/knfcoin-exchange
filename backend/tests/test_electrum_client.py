############################################################
#  [*] Electrum client tests — the transport
#
#  The REAL ElectrumClient over fake sockets — no server, no
#  certificates, fully deterministic: the endpoint read into
#  host and port, an answer matched to its request by id
#  across notifications and split reads, one connection
#  serving every request, a dropped or garbled connection
#  rebuilt once and the request retried, a second failure
#  naming the server, a server-side error never retried, and
#  the TLS handshake speaking first — the socket becoming the
#  session only once the server has answered it.
############################################################


import json
import ssl
import unittest
from unittest.mock import Mock, patch

from app.electrum_client import ELECTRUM_CLIENT_NAME, ELECTRUM_PROTOCOL_VERSION, ELECTRUM_TIMEOUT_S, ElectrumClient


# The endpoint the tests' client is built on — never contacted
ENDPOINT = '127.0.0.1:1'


# One JSON-RPC answer line, as an Electrum server writes it
def reply(request_id, result=None, error=None):
    message = {'jsonrpc': '2.0', 'id': request_id}
    if error:
        message['error'] = error
    else:
        message['result'] = result
    return (json.dumps(message) + '\n').encode('utf-8')








############################################################
# FakeSocket
############################################################
#
# The server's side of one connection: hands out the queued
# byte chunks on recv (an empty chunk is the server hanging
# up) and records every request the client sent.
#
# Used by:
#   - TestTransport, TestTheHandshake (below)
############################################################

class FakeSocket:

    def __init__(self, *chunks):
        self.chunks = list(chunks)
        self.requests = []
        self.closed = False

    def sendall(self, data):
        self.requests.append(json.loads(data.decode('utf-8')))

    def recv(self, _size):
        return self.chunks.pop(0) if self.chunks else b''

    def close(self):
        self.closed = True








############################################################
# TestTheEndpoint
############################################################
#
# What a new client takes from its endpoint string — and that
# it contacts nothing until the first request.
############################################################

class TestTheEndpoint(unittest.TestCase):

    def test_the_endpoint_is_read_into_host_and_port(self):
        client = ElectrumClient('158.129.172.247:50002')
        self.assertEqual((client.host, client.port), ('158.129.172.247', 50002))

    def test_nothing_is_contacted_before_the_first_request(self):
        with patch('app.electrum_client.socket.create_connection') as create:
            ElectrumClient(ENDPOINT)
        create.assert_not_called()








############################################################
# TestTransport
############################################################
#
# Requests over fake sockets: answers matched to requests by
# id, one connection serving every request, a broken
# connection rebuilt once, a server-side error never retried.
############################################################

class TestTransport(unittest.TestCase):

    def setUp(self):
        self.client = ElectrumClient(ENDPOINT)

    def connect_to(self, *sockets):
        # Every (re)connection hands out the next of the given sockets
        queue = list(sockets)

        def connect():
            self.client._sock = queue.pop(0)

        return patch.object(self.client, '_connect', side_effect=connect)

    def test_the_answer_is_matched_to_its_request_by_id(self):
        # A subscription notification and another request's answer are
        # skipped; an answer split across two reads is put back together
        notification = b'{"jsonrpc": "2.0", "method": "blockchain.headers.subscribe", "params": [{"height": 2203}]}\n'
        answer = reply(1, {'height': 2202})
        sock = FakeSocket(notification + reply(7, 'stale'), answer[:10], answer[10:])

        with self.connect_to(sock):
            self.assertEqual(self.client.request('blockchain.headers.subscribe', []), {'height': 2202})

        self.assertEqual(sock.requests, [
            {'jsonrpc': '2.0', 'id': 1, 'method': 'blockchain.headers.subscribe', 'params': []},
        ])

    def test_one_connection_serves_every_request(self):
        sock = FakeSocket(reply(1, {'height': 10}), reply(2, {'height': 11}))

        with self.connect_to(sock) as connect:
            self.assertEqual(self.client.request('blockchain.headers.subscribe', []), {'height': 10})
            self.assertEqual(self.client.request('blockchain.headers.subscribe', []), {'height': 11})

        self.assertEqual(connect.call_count, 1)

    def test_a_dropped_connection_is_rebuilt_once_and_the_request_retried(self):
        dropped = FakeSocket(b'')
        fresh = FakeSocket(reply(2, [{'tx_hash': 'aa' * 32, 'height': 5}]))

        with self.connect_to(dropped, fresh), self.assertLogs('exchange.electrum', 'WARNING'):
            history = self.client.request('blockchain.scripthash.get_history', ['scripthash'])

        self.assertEqual(history, [{'tx_hash': 'aa' * 32, 'height': 5}])
        self.assertTrue(dropped.closed)

    def test_a_garbled_answer_counts_as_a_broken_connection(self):
        with self.connect_to(FakeSocket(b'<html>\n'), FakeSocket(reply(2, None))), \
                self.assertLogs('exchange.electrum', 'WARNING'):
            self.assertIsNone(self.client.request('blockchain.scripthash.get_history', ['scripthash']))

    def test_a_second_failure_gives_up_naming_the_server(self):
        with self.connect_to(FakeSocket(b''), FakeSocket(b'')), self.assertLogs('exchange.electrum', 'WARNING'):
            with self.assertRaises(ConnectionError) as caught:
                self.client.request('blockchain.scripthash.get_history', ['scripthash'])

        self.assertEqual(str(caught.exception), 'Electrum 127.0.0.1:1 unreachable: Electrum connection closed by server')

    def test_an_error_answer_is_the_servers_word_and_not_retried(self):
        sock = FakeSocket(reply(1, error={'code': 1, 'message': 'unknown method'}))

        with self.connect_to(sock) as connect:
            with self.assertRaises(RuntimeError) as caught:
                self.client.request('blockchain.scripthash.get_history', ['scripthash'])

        self.assertEqual(connect.call_count, 1)
        self.assertIn('unknown method', str(caught.exception))
        self.assertFalse(sock.closed)








############################################################
# TestTheHandshake
############################################################
#
# Connecting for real, over a patched socket and TLS context:
# server.version goes first, certificates go unchecked, and
# only a socket whose handshake answered becomes the session.
############################################################

class TestTheHandshake(unittest.TestCase):

    def setUp(self):
        self.client = ElectrumClient(ENDPOINT)

    def connect_over(self, sock):
        # The TLS context hands the fake socket back as the encrypted one
        context = Mock()
        context.wrap_socket.return_value = sock
        create = patch('app.electrum_client.socket.create_connection', return_value='raw-socket')
        tls = patch('app.electrum_client.ssl.create_default_context', return_value=context)
        return context, create, tls

    def test_the_handshake_speaks_first_over_tls_without_certificate_checks(self):
        # Newer ElectrumX versions hang up unless server.version comes first;
        # the classroom servers have no CA-signed certificates
        sock = FakeSocket(reply(1, ['ElectrumX 1.16.0', '1.4']))
        context, create, tls = self.connect_over(sock)

        with create as connected, tls:
            self.client._connect()

        connected.assert_called_once_with(('127.0.0.1', 1), timeout=ELECTRUM_TIMEOUT_S)
        context.wrap_socket.assert_called_once_with('raw-socket', server_hostname='127.0.0.1')
        self.assertFalse(context.check_hostname)
        self.assertEqual(context.verify_mode, ssl.CERT_NONE)
        self.assertEqual([(r['method'], r['params']) for r in sock.requests],
                         [('server.version', [ELECTRUM_CLIENT_NAME, ELECTRUM_PROTOCOL_VERSION])])
        self.assertIs(self.client._sock, sock)

    def test_the_client_introduces_itself_as_the_exchange(self):
        self.assertEqual((ELECTRUM_CLIENT_NAME, ELECTRUM_PROTOCOL_VERSION), ('knf-exchange', '1.4'))

    def test_a_refused_handshake_leaves_no_session_behind(self):
        sock = FakeSocket(reply(1, error={'code': 1, 'message': 'unsupported protocol version'}))
        _, create, tls = self.connect_over(sock)

        with create, tls:
            with self.assertRaises(RuntimeError):
                self.client._connect()

        self.assertIsNone(self.client._sock)
        self.assertTrue(sock.closed)

    def test_after_a_refused_handshake_the_next_request_connects_afresh(self):
        refused = FakeSocket(reply(1, error={'code': 1, 'message': 'try again later'}))
        accepted = FakeSocket(reply(2, ['ElectrumX 1.16.0', '1.4']), reply(3, {'height': 7}))
        context = Mock()
        context.wrap_socket.side_effect = [refused, accepted]

        with patch('app.electrum_client.socket.create_connection', return_value='raw-socket'), \
                patch('app.electrum_client.ssl.create_default_context', return_value=context):
            with self.assertRaises(RuntimeError):
                self.client.request('blockchain.headers.subscribe', [])
            self.assertEqual(self.client.request('blockchain.headers.subscribe', []), {'height': 7})

        self.assertEqual([r['method'] for r in accepted.requests], ['server.version', 'blockchain.headers.subscribe'])
