"""docker-compose.yml is the supported way to run Trackaroo (Phase 6, 30-Sep).

Validated through `docker compose config`, which resolves defaults, relative
paths and the override merge exactly as a real deploy does. Skipped where the
docker CLI is absent; CI's ubuntu runner has it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.skipif(shutil.which("docker") is None, reason="docker CLI not installed")


def _config(tmp_path: Path, *, override: bool = False, env: dict | None = None) -> dict:
    # Copy into a scratch project so env_file (.env) can exist without
    # touching the repo's own .env, and so relative paths resolve there.
    shutil.copy(REPO / "docker-compose.yml", tmp_path / "docker-compose.yml")
    # A probe proves .env is loaded: `config` inlines env_file into environment.
    (tmp_path / ".env").write_text("TRACKAROO_ENV_PROBE=1\n", encoding="utf-8")
    files = ["-f", "docker-compose.yml"]
    if override:
        shutil.copy(REPO / "docker-compose.override.example.yml", tmp_path / "override.yml")
        files += ["-f", "override.yml"]
    result = subprocess.run(
        ["docker", "compose", *files, "config", "--format", "json"],
        cwd=tmp_path, capture_output=True, text=True, env={**_base_env(), **(env or {})},
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def _base_env() -> dict:
    import os
    env = dict(os.environ)
    for key in ("GIT_SHA", "TRACKAROO_PORT"):
        env.pop(key, None)
    return env


def test_one_service_named_trackaroo(tmp_path):
    cfg = _config(tmp_path)
    assert list(cfg["services"]) == ["trackaroo"]
    svc = cfg["services"]["trackaroo"]
    # Keeps every documented `docker exec trackaroo ...` working.
    assert svc["container_name"] == "trackaroo"
    assert svc["restart"] == "unless-stopped"


def test_db_data_and_logs_are_relative_bind_mounts(tmp_path):
    svc = _config(tmp_path)["services"]["trackaroo"]
    mounts = {v["target"]: v for v in svc["volumes"]}
    assert set(mounts) == {"/app/db", "/app/data", "/app/logs"}
    for target, name in (("/app/db", "db"), ("/app/data", "data"), ("/app/logs", "logs")):
        assert mounts[target]["type"] == "bind"
        assert Path(mounts[target]["source"]) == tmp_path / name


def test_build_stamp_defaults_to_dev_and_takes_git_sha(tmp_path):
    assert _config(tmp_path)["services"]["trackaroo"]["build"]["args"]["GIT_SHA"] == "dev"
    cfg = _config(tmp_path, env={"GIT_SHA": "abc1234"})
    assert cfg["services"]["trackaroo"]["build"]["args"]["GIT_SHA"] == "abc1234"


def test_port_env_file_timezone_and_log_rotation(tmp_path):
    svc = _config(tmp_path)["services"]["trackaroo"]
    assert svc["ports"][0]["target"] == 3000
    assert svc["ports"][0]["published"] == "3000"
    assert svc["environment"]["TRACKAROO_ENV_PROBE"] == "1"
    assert svc["environment"]["TZ"] == "Australia/Melbourne"
    assert svc["logging"]["driver"] == "json-file"
    assert svc["logging"]["options"]["max-size"] == "10m"


def test_never_disables_the_pipeline_or_the_image_healthcheck(tmp_path):
    svc = _config(tmp_path)["services"]["trackaroo"]
    assert "SKIP_PIPELINE" not in svc.get("environment", {})
    # The Dockerfile's HEALTHCHECK on /healthz applies unless compose overrides it.
    assert "healthcheck" not in svc


def test_watchtower_leaves_it_alone(tmp_path):
    labels = _config(tmp_path)["services"]["trackaroo"]["labels"]
    assert labels["com.centurylinklabs.watchtower.enable"] == "false"


def test_override_example_adds_only_the_mirror_mount(tmp_path):
    svc = _config(tmp_path, override=True)["services"]["trackaroo"]
    targets = {v["target"] for v in svc["volumes"]}
    assert targets == {"/app/db", "/app/data", "/app/logs", "/mnt/trackaroo-mirror"}


def test_the_real_override_file_is_gitignored():
    text = (REPO / ".gitignore").read_text(encoding="utf-8")
    assert "docker-compose.override.yml" in text.splitlines()
