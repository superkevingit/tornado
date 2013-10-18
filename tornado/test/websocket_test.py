from tornado.concurrent import Future
from tornado.httpclient import HTTPError, HTTPRequest
from tornado.log import gen_log
from tornado.testing import AsyncHTTPTestCase, gen_test, bind_unused_port, ExpectLog
from tornado.web import Application, RequestHandler
from tornado.websocket import WebSocketHandler, websocket_connect, WebSocketError

class TestWebSocketHandler(WebSocketHandler):
    """Base class for testing handlers that exposes the on_close event.

    This allows for deterministic cleanup of the associated socket.
    """
    def initialize(self, close_future):
        self.close_future = close_future

    def on_close(self):
        self.close_future.set_result(None)


class EchoHandler(TestWebSocketHandler):
    def on_message(self, message):
        self.write_message(message, isinstance(message, bytes))


class HeaderHandler(TestWebSocketHandler):
    def open(self):
        self.write_message(self.request.headers.get('X-Test', ''))


class NonWebSocketHandler(RequestHandler):
    def get(self):
        self.write('ok')


class WebSocketTest(AsyncHTTPTestCase):
    def get_app(self):
        self.close_future = Future()
        return Application([
            ('/echo', EchoHandler, dict(close_future=self.close_future)),
            ('/non_ws', NonWebSocketHandler),
            ('/header', HeaderHandler, dict(close_future=self.close_future)),
        ])

    @gen_test
    def test_websocket_gen(self):
        ws = yield websocket_connect(
            'ws://localhost:%d/echo' % self.get_http_port(),
            io_loop=self.io_loop)
        ws.write_message('hello')
        response = yield ws.read_message()
        self.assertEqual(response, 'hello')
        ws.close()
        yield self.close_future

    def test_websocket_callbacks(self):
        websocket_connect(
            'ws://localhost:%d/echo' % self.get_http_port(),
            io_loop=self.io_loop, callback=self.stop)
        ws = self.wait().result()
        ws.write_message('hello')
        ws.read_message(self.stop)
        response = self.wait().result()
        self.assertEqual(response, 'hello')
        ws.close()
        yield self.close_future

    @gen_test
    def test_websocket_http_fail(self):
        with self.assertRaises(HTTPError) as cm:
            yield websocket_connect(
                'ws://localhost:%d/notfound' % self.get_http_port(),
                io_loop=self.io_loop)
        self.assertEqual(cm.exception.code, 404)

    @gen_test
    def test_websocket_http_success(self):
        with self.assertRaises(WebSocketError):
            yield websocket_connect(
                'ws://localhost:%d/non_ws' % self.get_http_port(),
                io_loop=self.io_loop)

    @gen_test
    def test_websocket_network_fail(self):
        sock, port = bind_unused_port()
        sock.close()
        with self.assertRaises(HTTPError) as cm:
            with ExpectLog(gen_log, ".*"):
                yield websocket_connect(
                    'ws://localhost:%d/' % port,
                    io_loop=self.io_loop,
                    connect_timeout=0.01)
        self.assertEqual(cm.exception.code, 599)

    @gen_test
    def test_websocket_close_buffered_data(self):
        ws = yield websocket_connect(
            'ws://localhost:%d/echo' % self.get_http_port())
        ws.write_message('hello')
        ws.write_message('world')
        ws.stream.close()
        yield self.close_future

    @gen_test
    def test_websocket_headers(self):
        # Ensure that arbitrary headers can be passed through websocket_connect.
        ws = yield websocket_connect(
            HTTPRequest('ws://localhost:%d/header' % self.get_http_port(),
                        headers={'X-Test': 'hello'}))
        response = yield ws.read_message()
        self.assertEqual(response, 'hello')
        ws.close()
        yield self.close_future
