"""Local HTTP peer: exercises public clients without production services."""
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
import json


@contextmanager
def server(respond):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def handle_request(self):
            body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
            response = respond(self.command, self.path, body, self.headers)
            if response is None:
                self.connection.close()
                return
            status, payload, headers = response
            raw = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        do_GET = do_POST = do_PUT = do_PATCH = handle_request

    peer = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = Thread(target=peer.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{peer.server_port}'
    finally:
        peer.shutdown()
        peer.server_close()
        thread.join()
