"""Benign image and HTTP compatibility, also runnable inside the browser image."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread

import pytest
import requests


@pytest.mark.parametrize("image_format", ["PNG", "TIFF"])
def test_browser_pillow_rgb_image_round_trip(image_format: str) -> None:
    """Exercise ordinary in-memory image handling across the Pillow upgrade."""
    image = pytest.importorskip("PIL.Image")
    original = image.new("RGB", (32, 16), color=(12, 34, 56))
    encoded = BytesIO()
    original.save(encoded, format=image_format)
    encoded.seek(0)
    with image.open(encoded) as restored:
        restored.load()
        assert restored.mode == "RGB" and restored.size == (32, 16)
        assert restored.getpixel((0, 0)) == (12, 34, 56)
        resized = restored.resize((16, 8), resample=image.Resampling.LANCZOS)
        assert resized.getpixel((0, 0)) == (12, 34, 56)


def test_browser_requests_urllib3_pool_handles_regular_and_chunked_responses() -> None:
    """Read bounded synthetic JSON through Requests and its urllib3 pool."""
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            payload = b'{"result":"synthetic-ok"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if self.path == "/stream":
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                for part in (payload[:8], payload[8:]):
                    self.wfile.write(f"{len(part):x}\r\n".encode() + part + b"\r\n")
                self.wfile.write(b"0\r\n\r\n")
            else:
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with requests.Session() as session:
                session.trust_env = False
                url = f"http://127.0.0.1:{server.server_port}"
                assert session.get(url, timeout=3).json() == {"result": "synthetic-ok"}
                with session.get(url + "/stream", stream=True, timeout=3) as response:
                    assert b"".join(response.iter_content(chunk_size=4)) == b'{"result":"synthetic-ok"}'
        finally:
            server.shutdown()
            thread.join(timeout=3)
