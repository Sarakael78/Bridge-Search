import subprocess
from types import SimpleNamespace

from bridge_search import config
from bridge_search.health import check_health


def test_get_wsl_host_ip_mocked(tmp_path, monkeypatch):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 172.20.160.1\n")

    monkeypatch.setattr(config.os.path, "exists", lambda path: True if path == "/etc/resolv.conf" else config.os.path.exists(path))

    real_open = open

    def scoped_open(path, *args, **kwargs):
        if str(path) == "/etc/resolv.conf":
            return real_open(str(resolv), *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(config, "open", scoped_open, raising=False)
    import builtins
    monkeypatch.setattr(builtins, "open", scoped_open)

    assert config.get_wsl_host_ip() == "172.20.160.1"


def test_check_health_basic(monkeypatch):
    monkeypatch.setattr(config, "backend_enabled", lambda name: False)

    res = check_health()
    assert res["overall_success"] is False
    assert any(err["code"] == "no_backends_enabled" for err in res["errors"])


def test_check_health_wsl_only(monkeypatch):
    """Mock subprocess.run for which find/grep so test works in any CI environment."""
    monkeypatch.setattr(config, "backend_enabled", lambda name: name in ("wsl_find", "wsl_grep"))

    def fake_run(cmd, capture_output=False, timeout=None, **kwargs):
        if cmd == ["which", "find"] or cmd == ["which", "grep"]:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return subprocess.run(cmd, capture_output=capture_output, timeout=timeout, **kwargs)

    import bridge_search.health as health_mod
    monkeypatch.setattr(health_mod.subprocess, "run", fake_run)

    res = check_health()
    assert res["backends"]["wsl_find"]["status"] == "ok"
    assert res["backends"]["wsl_grep"]["status"] == "ok"
    assert res["overall_success"] is True
