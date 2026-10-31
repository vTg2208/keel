import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from infra.jenkins.download_plugins import download


def test_corrupt_cached_plugin_is_replaced_after_bad_network_response(tmp_path):
    artifact = b"a complete pinned plugin artifact"
    item = {"name": "example", "version": "1.0", "sha256": hashlib.sha256(artifact).hexdigest()}
    (tmp_path / "example-1.0.jpi").write_bytes(b"corrupt cache")

    class Handler(BaseHTTPRequestHandler):
        requests = 0

        def do_GET(self):
            assert self.path == "/example/1.0/example.hpi"
            Handler.requests += 1
            body = b"truncated" if Handler.requests == 1 else artifact
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        path = download(item, tmp_path, f"http://127.0.0.1:{server.server_port}", retry_delay=0)
        assert path.read_bytes() == artifact
        assert Handler.requests == 2
        # A verified cache must work even when the remote endpoint is unavailable.
        assert download(item, tmp_path, "http://127.0.0.1:1").read_bytes() == artifact
    finally:
        server.shutdown()
        server.server_close()
