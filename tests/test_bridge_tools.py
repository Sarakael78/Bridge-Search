"""Tests for bridge modules and public contract."""

import copy
import json
from types import SimpleNamespace

from bridge_search import bridge_tools
from bridge_search import config as bridge_config
from bridge_search import file_ops
from bridge_search import path_policy
from bridge_search import search_backends
import scripts.setup_skill as setup_skill


def test_auto_target_env_windows_paths_use_wsl_branch() -> None:
    assert path_policy.auto_target_env(r"C:\Users\test") == "wsl"
    assert path_policy.auto_target_env("c:/temp/file.txt") == "wsl"
    assert path_policy.auto_target_env(r"D:\Docs\note.txt") == "wsl"
    assert path_policy.auto_target_env(r"\\server\share\file.txt") == "wsl"


def test_auto_target_env_unix_paths_use_windows_branch() -> None:
    assert path_policy.auto_target_env("/mnt/c/Users") == "windows"
    assert path_policy.auto_target_env("/home/user/proj") == "windows"


def test_everything_search_arg_partial_wraps() -> None:
    assert search_backends._everything_search_arg("foo", False) == "*foo*"
    assert search_backends._everything_search_arg("  bar  ", False) == "*bar*"


def test_parse_allowed_prefixes_env_supports_windows_drive_letters(monkeypatch) -> None:
    mapping = {r"C:\Users\david\Documents": "/mnt/c/Users/david/Documents"}
    monkeypatch.setenv("BRIDGE_SEARCH_ALLOWED_PREFIXES", r"C:\Users\david\Documents;/tmp/work")
    monkeypatch.setattr(path_policy, "resolve_path", lambda path, env: mapping.get(path, path))
    assert path_policy.parse_allowed_prefixes_env() == ["/mnt/c/Users/david/Documents", "/tmp/work"]


def test_allowed_prefixes_config_supports_windows_paths(monkeypatch, tmp_path) -> None:
    mapping = {r"C:\Users\david\Documents": "/mnt/c/Users/david/Documents"}
    config_path = tmp_path / "bridge-search.config.json"
    config_path.write_text(
        json.dumps({"security": {"allowed_prefixes": [r"C:\Users\david\Documents"]}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("BRIDGE_SEARCH_CONFIG", str(config_path))
    monkeypatch.setattr(path_policy, "resolve_path", lambda path, env: mapping.get(path, path))
    bridge_config.get_bridge_config(reload=True)
    assert path_policy.is_path_allowed("/mnt/c/Users/david/Documents/note.txt", "wsl") is True
    assert path_policy.is_path_allowed("/mnt/c/Users/david/Desktop/note.txt", "wsl") is False


def test_custom_restricted_prefixes_support_windows_paths(monkeypatch, tmp_path) -> None:
    mapping = {r"C:\Users\david\Secret": "/mnt/c/Users/david/Secret"}
    config_path = tmp_path / "bridge-search.config.json"
    config_path.write_text(
        json.dumps(
            {
                "security": {
                    "path_denylist": "custom",
                    "custom_restricted_prefixes": [r"C:\Users\david\Secret"],
                }
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BRIDGE_SEARCH_CONFIG", str(config_path))
    monkeypatch.setattr(path_policy, "resolve_path", lambda path, env: mapping.get(path, path))
    bridge_config.get_bridge_config(reload=True)
    assert path_policy.is_path_allowed("/mnt/c/Users/david/Secret/file.txt", "wsl") is False
    assert path_policy.is_path_allowed("/mnt/c/Users/david/Public/file.txt", "wsl") is True


def test_backend_enabled_env_overrides_config(monkeypatch) -> None:
    monkeypatch.delenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", raising=False)
    cfg = copy.deepcopy(bridge_config._DEFAULTS)
    cfg["backends"] = {**cfg["backends"], "everything": False}
    bridge_config._cfg_cache = cfg
    try:
        monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "1")
        assert bridge_tools.backend_enabled("everything") is True
        monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "0")
        assert bridge_tools.backend_enabled("everything") is False
    finally:
        bridge_config._cfg_cache = None


def test_anytxt_url_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://host.docker.internal:9921")
    assert bridge_tools.anytxt_search_url() == "http://host.docker.internal:9921/search"


def test_system_locator_zero_hit_is_success(monkeypatch) -> None:
    monkeypatch.setattr(bridge_tools, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(bridge_tools, "backend_enabled", lambda name: name == "everything")

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"", stderr=b"")

    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("missing.docx", target_env="windows")
    assert result["success"] is True
    assert result["results"] == []
    assert result["errors"] == []
    assert result["meta"]["total_found"] == 0


def test_system_locator_blank_query_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: True)
    result = bridge_tools.system_locator("   ", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "query_required"


def test_system_locator_translates_windows_results(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: "/mnt/d/Docs/file.txt" if path == r"D:\Docs\file.txt" and env == "wsl" else path)
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: False)

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"D:\\Docs\\file.txt\n", stderr=b"")

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("file.txt", target_env="windows")
    assert result["success"] is True
    assert result["results"][0]["raw_path"] == r"D:\Docs\file.txt"
    assert result["results"][0]["path"] == "/mnt/d/Docs/file.txt"


def test_system_locator_backend_error_has_code(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: None)
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    result = bridge_tools.system_locator("file.txt", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "backend_unavailable"


def test_system_locator_uses_everything_native_paging_when_supported(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: True)
    seen = {}

    payload = json.dumps(
        [
            {"filename": r"D:\Docs\one.txt"},
            {"filename": r"D:\Docs\two.txt"},
            {"filename": r"D:\Docs\three.txt"},
        ]
    ).encode("utf-8")

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=payload, stderr=b"")

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: f"/mnt/d/Docs/{path.split('\\')[-1]}" if env == "wsl" else path)
    result = bridge_tools.system_locator("txt", target_env="windows", limit=2, offset=5)
    assert "-viewport-offset" in seen["cmd"]
    assert "-viewport-count" in seen["cmd"]
    assert result["meta"]["everything_native_paging"] is True
    assert result["meta"]["has_more"] is True
    assert result["meta"]["total_found_exact"] is False
    assert result["meta"]["total_found"] == 7
    assert result["meta"]["returned_count"] == 2
    assert len(result["results"]) == 2


def test_non_native_locator_reports_exact_total_when_known(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: False)
    monkeypatch.setattr(search_backends, "path_allowed_for_search_result", lambda path: True)

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"D:\\Docs\\one.txt\nD:\\Docs\\two.txt\n", stderr=b"")

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("txt", target_env="windows", limit=5, offset=0)
    assert result["meta"]["total_found"] == 2
    assert result["meta"]["returned_count"] == 2
    assert result["meta"]["total_found_exact"] is True


def test_content_locator_anytxt_uses_configured_runtime_url(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9921/api")

    class FakeResponse:
        status = 200
        def __enter__(self):
            return self
        def __exit__(self, exc_type, exc, tb):
            return False
        def read(self, _max_bytes):
            return b'{"results": [{"path": "C:\\\\Users\\\\david\\\\memo.txt", "snippet": "needle here"}]}'

    seen = {}
    def fake_urlopen(req, timeout=5):
        seen["url"] = req.full_url
        return FakeResponse()

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: "/mnt/c/Users/david/memo.txt" if path == r"C:\Users\david\memo.txt" and env == "wsl" else path)
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert seen["url"] == "http://winhost:9921/api/search?q=needle"
    assert result["results"][0]["path"] == "/mnt/c/Users/david/memo.txt"


def test_content_locator_blank_query_is_rejected(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: True)
    result = bridge_tools.content_locator("   ", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "query_required"


def test_wsl_grep_command_excludes_mnt_when_searching_root() -> None:
    cmd = search_backends._wsl_grep_command("needle", "/")
    assert "--exclude-dir=mnt" in cmd
    assert "--exclude-dir=/mnt" not in cmd


def test_manage_file_contract_read_and_encoding(tmp_path) -> None:
    target = tmp_path / "note.txt"
    bridge_tools.hybrid_file_io("write", str(target), content="hello", is_confirmed=True)
    result = bridge_tools.hybrid_file_io("read", str(target))
    assert set(result.keys()) == {"success", "results", "errors", "warnings", "meta"}
    assert result["results"][0]["content"] == "hello"
    assert result["results"][0]["encoding"] == "utf-8"


def test_manage_file_read_cp1252_text(tmp_path) -> None:
    target = tmp_path / "latin1.txt"
    target.write_bytes("café".encode("cp1252"))
    result = bridge_tools.hybrid_file_io("read", str(target))
    assert result["success"] is True
    assert result["results"][0]["content"] == "café"
    assert result["results"][0]["encoding"] == "cp1252"


def test_manage_file_read_utf16_text(tmp_path) -> None:
    target = tmp_path / "utf16.txt"
    target.write_text("hello ☕", encoding="utf-16")
    result = bridge_tools.hybrid_file_io("read", str(target))
    assert result["success"] is True
    assert result["results"][0]["encoding"] == "utf-16"


def test_manage_file_requires_confirmation_for_write(tmp_path) -> None:
    target = tmp_path / "note.txt"
    result = bridge_tools.hybrid_file_io("write", str(target), content="hello", is_confirmed=False)
    assert result["success"] is False
    assert result["errors"][0]["code"] == "write_confirmation_required"


def test_manage_file_write_missing_parent_returns_structured_error(tmp_path) -> None:
    target = tmp_path / "missing" / "note.txt"
    result = bridge_tools.hybrid_file_io("write", str(target), content="hello", is_confirmed=True)
    assert result["success"] is False
    assert result["errors"][0]["code"] == "destination_parent_missing"


def test_manage_file_write_mode_append_is_explicit(tmp_path) -> None:
    target = tmp_path / "note.txt"
    bridge_tools.hybrid_file_io("write", str(target), content="hello", is_confirmed=True)
    bridge_tools.hybrid_file_io("write", str(target), content=" world", is_confirmed=True, write_mode="append")
    result = bridge_tools.hybrid_file_io("read", str(target))
    assert result["results"][0]["content"] == "hello world"


def test_manage_file_invalid_write_mode_is_rejected(tmp_path) -> None:
    target = tmp_path / "note.txt"
    result = bridge_tools.hybrid_file_io("write", str(target), content="hello", is_confirmed=True, write_mode="banana")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "invalid_write_mode"


def test_manage_file_copy_requires_explicit_overwrite(tmp_path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("source", encoding="utf-8")
    dst.write_text("dest", encoding="utf-8")
    result = bridge_tools.hybrid_file_io("copy", str(src), destination_path=str(dst))
    assert result["success"] is False
    assert result["errors"][0]["code"] == "destination_exists"


def test_manage_file_copy_and_move_overwrite(tmp_path) -> None:
    src = tmp_path / "src.txt"
    dst = tmp_path / "dst.txt"
    src.write_text("source", encoding="utf-8")
    dst.write_text("dest", encoding="utf-8")
    copy_result = bridge_tools.hybrid_file_io("copy", str(src), destination_path=str(dst), overwrite=True)
    assert copy_result["success"] is True
    moved_src = tmp_path / "move.txt"
    moved_src.write_text("moved", encoding="utf-8")
    move_result = bridge_tools.hybrid_file_io("move", str(moved_src), destination_path=str(dst), overwrite=True)
    assert move_result["success"] is True
    assert dst.read_text(encoding="utf-8") == "moved"


def test_manage_file_symlink_policy(tmp_path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("x", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    blocked = bridge_tools.hybrid_file_io("write", str(link), content="y", is_confirmed=True, overwrite=True)
    assert blocked["success"] is False
    assert blocked["errors"][0]["code"] == "symlink_blocked"
    delete_result = bridge_tools.hybrid_file_io("delete", str(link), is_confirmed=True)
    assert delete_result["success"] is True
    assert target.exists()


def test_manage_file_delete_home_directory_blocked(monkeypatch, tmp_path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(file_ops.os.path, "expanduser", lambda path: str(home) if path == "~" else path)
    result = bridge_tools.hybrid_file_io("delete", str(home), is_confirmed=True)
    assert result["success"] is False
    assert result["errors"][0]["code"] == "home_delete_blocked"


def test_map_directory_contract(tmp_path) -> None:
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    result = bridge_tools.catalog_directory(str(root))
    assert result["success"] is True
    assert set(result.keys()) == {"success", "results", "errors", "warnings", "meta"}
    assert result["results"][0]["type"] == "directory_map"
    assert "a.txt" in result["results"][0]["text"]


def test_map_directory_exact_page_reports_no_more(tmp_path) -> None:
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    result = bridge_tools.catalog_directory(str(root), limit=2)
    assert result["meta"]["total_found"] == 2
    assert result["meta"]["returned_count"] == 2
    assert result["meta"]["has_more"] is False
    assert "truncated" not in result["meta"]


def test_map_directory_page_boundary_reports_more(tmp_path) -> None:
    root = tmp_path / "folder"
    root.mkdir()
    (root / "a.txt").write_text("x", encoding="utf-8")
    (root / "b.txt").write_text("y", encoding="utf-8")
    result = bridge_tools.catalog_directory(str(root), limit=2)
    assert result["meta"]["total_found"] == 3
    assert result["meta"]["returned_count"] == 2
    assert result["meta"]["has_more"] is True
    assert result["meta"]["truncated"] is True
    assert result["meta"]["total_found_is_lower_bound"] is True


def test_integration_like_everything_error(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/fake/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: False)
    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=2, stdout=b"", stderr=b"fatal")
    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("x", target_env="windows")
    assert result["errors"][0]["code"] == "backend_error"


def test_integration_like_anytxt_invalid_json(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")
    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, _max_bytes): return b"not-json"
    monkeypatch.setattr(search_backends.urllib.request, "urlopen", lambda req, timeout=5: FakeResponse())
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "invalid_response"


def test_integration_like_path_translation_failure_warns(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: False)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: path)
    monkeypatch.setattr(path_policy, "resolve_path", lambda path, env: path)
    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"D:\\Docs\\file.txt\n", stderr=b"")
    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("file.txt", target_env="windows")
    assert result["success"] is True
    assert result["warnings"][0]["code"] == "path_translation_failed"


def test_backend_timeout_surfaces_structured_error(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/fake/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "everything")
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: False)

    def fake_run(*args, **kwargs):
        raise search_backends.subprocess.TimeoutExpired(cmd=args[0], timeout=kwargs.get("timeout", 1))

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    result = bridge_tools.system_locator("x", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "backend_timeout"


def test_anytxt_timeout_surfaces_structured_timeout(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")

    class TimeoutLike(TimeoutError):
        pass

    def fake_urlopen(req, timeout=5):
        raise TimeoutLike("timed out")

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "backend_timeout"


def test_setup_skill_normalizes_and_persists_anytxt_url(tmp_path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = setup_skill._write_runtime_config(str(repo_root), "http://winhost:9921")
    payload = (repo_root / "config" / "bridge-search.config.json").read_text(encoding="utf-8")
    assert config_path.endswith("bridge-search.config.json")
    assert '"anytxt_url": "http://winhost:9921/search"' in payload


def test_setup_skill_mcporter_register_replaces_existing(monkeypatch, tmp_path) -> None:
    persist = tmp_path / "mcporter.json"
    calls = []
    def fake_run_command_capture(cmd, timeout=30):
        calls.append(cmd)
        if cmd[:4] == ["mcporter", "config", "add", "bridge-search"] and len(calls) == 1:
            return 1, "", "already exists"
        return 0, "ok", ""
    monkeypatch.setattr(setup_skill, "run_command_capture", fake_run_command_capture)
    ok = setup_skill._mcporter_register("python3", "/tmp/server.py", str(persist))
    assert ok is True
    assert calls[1][:4] == ["mcporter", "config", "remove", "bridge-search"]
    assert calls[2][:4] == ["mcporter", "config", "add", "bridge-search"]


def test_everything_supports_native_paging_from_help(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/fake/es.exe")
    search_backends._EVERYTHING_HELP_CACHE = None

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        return SimpleNamespace(returncode=0, stdout=b"-viewport-offset\n-viewport-count\n", stderr=b"")

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    assert search_backends.everything_supports_native_paging() is True
