import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from stubs.stub_server import StubHandler


@pytest.fixture
def stub_url():
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_health_returns_ok(stub_url):
    with urllib.request.urlopen(f"{stub_url}/health", timeout=3) as resp:
        assert resp.status == 200
        assert json.load(resp)["status"] == "ok"


def test_other_paths_return_501(stub_url):
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{stub_url}/categorize", timeout=3)
    assert exc.value.code == 501
