"""Guards that keep tests and CI from ever touching a retailer (#13)."""
import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def test_the_suite_blocks_outbound_connections():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        with pytest.raises(RuntimeError, match="Blocked outbound connection"):
            s.connect(("93.184.216.34", 80))
    finally:
        s.close()


def test_loopback_is_still_allowed():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        client.connect(server.getsockname())
    finally:
        client.close()
        server.close()


def test_skip_pipeline_stops_before_any_scrape():
    text = (REPO / "deploy" / "entrypoint-single.sh").read_text(encoding="utf-8")
    knob = text.index('if [ "${SKIP_PIPELINE:-0}" = "1" ]')
    assert knob < text.index("run_pipeline --pending-only")
    assert knob < text.index("spec_sync_loop &")
    assert knob > text.index("node web/server.js &")


def test_ci_workflow_boots_the_image_offline():
    ci = (REPO / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "--network none" in ci
    assert "SKIP_PIPELINE=1" in ci
    assert "python -m pytest -q" in ci
    assert "npm run test:e2e" in ci
    assert "node server.js" in ci
