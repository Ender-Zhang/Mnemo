from __future__ import annotations

from http import HTTPStatus
import re
from threading import Thread
import tempfile
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class MemoryWebServiceTests(unittest.TestCase):
    def test_webui_static_routes_are_public_but_api_keeps_token_auth(self) -> None:
        from mnemo_memory.interfaces.web import MemoryWebConfig, build_http_server

        with tempfile.TemporaryDirectory() as tmp:
            server = build_http_server(
                MemoryWebConfig(state_dir=tmp, host="127.0.0.1", port=0, auth_token="dev-token")
            )
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://{server.server_address[0]}:{server.server_address[1]}"

                index = _get(base + "/")
                self.assertEqual(index.status, HTTPStatus.OK)
                self.assertIn("text/html", index.content_type)
                self.assertIn("Mnemo Memory", index.body)

                fallback = _get(base + "/settings")
                self.assertEqual(fallback.status, HTTPStatus.OK)
                self.assertIn("text/html", fallback.content_type)

                with self.assertRaises(HTTPError) as unauthorized:
                    _get(base + "/api/schema")
                self.assertEqual(unauthorized.exception.code, HTTPStatus.UNAUTHORIZED)

                schema = _get(base + "/api/schema", token="dev-token")
                self.assertEqual(schema.status, HTTPStatus.OK)
                self.assertIn("application/json", schema.content_type)

                asset_paths = re.findall(r'/(assets/[^"]+)', index.body)
                self.assertTrue(asset_paths)
                asset = _get(f"{base}/{asset_paths[0]}")
                self.assertEqual(asset.status, HTTPStatus.OK)
                self.assertNotIn("application/json", asset.content_type)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_webui_rejects_static_path_traversal(self) -> None:
        from mnemo_memory.interfaces.web import MemoryWebConfig, build_http_server

        with tempfile.TemporaryDirectory() as tmp:
            server = build_http_server(MemoryWebConfig(state_dir=tmp, host="127.0.0.1", port=0))
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://{server.server_address[0]}:{server.server_address[1]}"

                with self.assertRaises(HTTPError) as not_found:
                    _get(base + "/assets/%2e%2e/web.py")
                self.assertEqual(not_found.exception.code, HTTPStatus.NOT_FOUND)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


class HttpResponse:
    def __init__(self, *, status: int, content_type: str, body: str) -> None:
        self.status = status
        self.content_type = content_type
        self.body = body


def _get(url: str, *, token: str | None = None) -> HttpResponse:
    request = Request(url)
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urlopen(request, timeout=5) as response:
        return HttpResponse(
            status=response.status,
            content_type=response.headers.get("Content-Type", ""),
            body=response.read().decode("utf-8", errors="replace"),
        )


if __name__ == "__main__":
    unittest.main()
