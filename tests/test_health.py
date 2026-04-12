import os
from bridge_search.health import check_health
from bridge_search import config

def test_get_wsl_host_ip_mocked(tmp_path, monkeypatch):
    resolv = tmp_path / "resolv.conf"
    resolv.write_text("nameserver 172.20.160.1\n")
    
    def mock_exists(path):
        if path == "/etc/resolv.conf":
            return True
        return os.path.exists(path)

    # We need to mock open for /etc/resolv.conf specifically
    import builtins
    real_open = builtins.open
    
    def mock_open(path, *args, **kwargs):
        if path == "/etc/resolv.conf":
            return real_open(resolv, *args, **kwargs)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(os.path, "exists", mock_exists)
    monkeypatch.setattr(builtins, "open", mock_open)
    
    assert config.get_wsl_host_ip() == "172.20.160.1"

def test_check_health_basic(monkeypatch):
    # Disable all backends to get a predictable failed state
    monkeypatch.setattr(config, "backend_enabled", lambda name: False)
    
    res = check_health()
    assert res["overall_success"] is False
    assert any(err["code"] == "no_backends_enabled" for err in res["errors"])

def test_check_health_wsl_only(monkeypatch):
    monkeypatch.setattr(config, "backend_enabled", lambda name: name in ("wsl_find", "wsl_grep"))
    
    res = check_health()
    # On a standard linux system, find and grep should be present
    assert res["backends"]["wsl_find"]["status"] == "ok"
    assert res["backends"]["wsl_grep"]["status"] == "ok"
    assert res["overall_success"] is True
