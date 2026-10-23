############################################################
#  [*] Electrum client
#
#  A minimal ElectrumX client: one TLS socket, newline-
#  delimited JSON-RPC. Knows NOTHING about the exchange, its
#  wallets or its chains — it gets an endpoint string and
#  talks protocol; what a query means, and what its answer is
#  worth, is the wallet's business. The classroom servers run
#  without CA-signed certificates, so certificate checks are
#  off.
#
#  Built to stay alive: one instance per chain lives as long
#  as its wallet. A lock serializes the strict request /
#  response protocol across the threads sharing it (the
#  worker plus the occasional API request — contention is
#  negligible), and reusing the socket spares a TLS handshake
#  per query. A transport failure — a dropped socket, a
#  timeout, a garbled answer — rebuilds the connection and
#  retries the request ONCE before giving up with a
#  ConnectionError naming the server; safe even for a
#  broadcast, because re-sending the same raw transaction is
#  idempotent (same txid). An error answer is the server's
#  word and is never retried.
#
#  Used by:
#    - app/wallet.py — one client per ExchangeWallet
############################################################


import ssl
import json
import socket
import logging
import threading


logger = logging.getLogger('exchange.electrum')


# The name and protocol version announced in the server.version
# handshake — newer ElectrumX releases serve no session that does
# not introduce itself first
ELECTRUM_CLIENT_NAME = 'knf-exchange'
ELECTRUM_PROTOCOL_VERSION = '1.4'

# Every socket operation (connect, send, recv) gets this deadline,
# so a hung server can never freeze the worker thread indefinitely.
ELECTRUM_TIMEOUT_S = 15








############################################################
# ElectrumClient
############################################################
#
# The client itself; see the file header for the full story.
# Its public surface is request() — everything else is
# connection plumbing.
#
# Used by:
#   - app/wallet.py — ExchangeWallet keeps one per chain
############################################################

class ElectrumClient:






    ############################################################
    # __init__
    ############################################################
    #
    # endpoint is the chain's 'host:port' string. Nothing is
    # contacted yet: the first request connects.
    #
    # Used by:
    #   - app/wallet.py — ExchangeWallet.__init__
    ############################################################

    def __init__(self, endpoint: str):
        self.host, port = endpoint.split(':')
        self.port = int(port)

        # The open session, the bytes read past the last answer, and the id
        # of the last request
        self._sock = None
        self._recv_buffer = b''
        self._request_id = 0

        # The protocol is strict request/response over one socket —
        # concurrent threads must take turns
        self._lock = threading.Lock()






    ############################################################
    # request
    ############################################################
    #
    # One Electrum call: connect on first use, then one locked
    # round trip, answering the call's result. A stale
    # connection (a server restart, an idle timeout) or a
    # garbled answer fails the first attempt, gets rebuilt and
    # the request is retried once on the fresh socket; a second
    # failure raises ConnectionError naming the server. An
    # error answer raises RuntimeError at once — the server
    # answered, asking again would not change it.
    #
    # Used by:
    #   - app/wallet.py — every chain query and the broadcast
    ############################################################

    def request(self, method: str, params: list):
        with self._lock:
            for attempt in (1, 2):
                try:
                    if self._sock is None:
                        self._connect()
                    return self._send_and_wait(method, params)

                except RuntimeError:
                    # A real answer from the server (an Electrum-level
                    # error): the connection itself is fine, don't retry.
                    raise

                except (OSError, ConnectionError, TimeoutError, json.JSONDecodeError) as e:
                    self._disconnect()
                    if attempt == 2:
                        raise ConnectionError(f'Electrum {self.host}:{self.port} unreachable: {e}')
                    logger.warning('Electrum connection to %s:%s failed (%s), reconnecting',
                                   self.host, self.port, e)






    ############################################################
    # _connect
    ############################################################
    #
    # Opens the TLS connection; the caller holds the lock. The
    # server.version handshake goes out first thing — newer
    # ElectrumX versions close the session unless it is the
    # FIRST message. The socket counts as the session only once
    # the handshake has answered: a refused or broken handshake
    # leaves nothing behind for the next request to reuse.
    #
    # Used by:
    #   - request (above) — on first use and after a broken
    #     connection
    ############################################################

    def _connect(self):
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE

        sock = socket.create_connection((self.host, self.port), timeout=ELECTRUM_TIMEOUT_S)
        self._sock = context.wrap_socket(sock, server_hostname=self.host)
        self._recv_buffer = b''

        try:
            self._send_and_wait('server.version', [ELECTRUM_CLIENT_NAME, ELECTRUM_PROTOCOL_VERSION])
        except BaseException:
            self._disconnect()
            raise
        logger.debug('Connected to Electrum %s:%s', self.host, self.port)






    ############################################################
    # _disconnect
    ############################################################
    #
    # Drops the connection and whatever was half-read from it,
    # so the next request starts on a fresh one. An error while
    # closing an already broken socket means nothing.
    #
    # Used by:
    #   - request, _connect (above) — after a failure
    ############################################################

    def _disconnect(self):
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None
        self._recv_buffer = b''






    ############################################################
    # _send_and_wait
    ############################################################
    #
    # One JSON-RPC round trip on the open socket; the caller
    # holds the lock. The request goes out as one newline-
    # terminated line, and lines are read until the one
    # answering it arrives. An error answer raises RuntimeError
    # — the server's word, not a transport failure; a closed
    # socket raises ConnectionError.
    #
    # Used by:
    #   - request, _connect (above) — the call, the handshake
    ############################################################

    def _send_and_wait(self, method: str, params: list):
        # Replies are matched by id because the server may interleave
        # subscription notifications (which have no id) with our responses.
        self._request_id += 1
        request_id = self._request_id

        request = {'jsonrpc': '2.0', 'id': request_id, 'method': method, 'params': params}
        self._sock.sendall((json.dumps(request) + '\n').encode('utf-8'))

        while True:
            while b'\n' in self._recv_buffer:
                line, self._recv_buffer = self._recv_buffer.split(b'\n', 1)
                message = json.loads(line.decode('utf-8'))
                if message.get('id') == request_id:
                    if message.get('error'):
                        raise RuntimeError(f"Electrum error: {message['error']}")
                    return message.get('result')

            chunk = self._sock.recv(4096)
            if not chunk:
                raise ConnectionError('Electrum connection closed by server')
            self._recv_buffer += chunk
