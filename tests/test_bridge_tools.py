"""Tests for bridge modules and public contract."""

import copy
import importlib
import json
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from bridge_search import bridge_tools
from bridge_search import config as bridge_config
from bridge_search import file_ops
from bridge_search import path_policy
from bridge_search import search_backends
import scripts.setup_skill as setup_skill


def _command_text(cmd) -> str:
    """Flatten subprocess argv for assertions across direct and PowerShell-wrapped calls."""
    if isinstance(cmd, (list, tuple)):
        return "\n".join(str(part) for part in cmd)
    return str(cmd)


def _load_server_module_with_fake_mcp(monkeypatch):
    fake_fastmcp = types.ModuleType("mcp.server.fastmcp")

    class FakeFastMCP:
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

        def tool(self):
            def decorator(fn):
                return fn

            return decorator

        def run(self, *args, **kwargs):
            return None

    fake_fastmcp.FastMCP = FakeFastMCP
    fake_server = types.ModuleType("mcp.server")
    fake_server.fastmcp = fake_fastmcp
    fake_mcp = types.ModuleType("mcp")
    fake_mcp.server = fake_server
    monkeypatch.setitem(sys.modules, "mcp", fake_mcp)
    monkeypatch.setitem(sys.modules, "mcp.server", fake_server)
    monkeypatch.setitem(sys.modules, "mcp.server.fastmcp", fake_fastmcp)
    return importlib.import_module("bridge_search.server")


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
    monkeypatch.setattr(bridge_config, "get_bridge_config", lambda reload=False: cfg)
    monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "1")
    assert bridge_tools.backend_enabled("everything") is True
    monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "0")
    assert bridge_tools.backend_enabled("everything") is False


def test_anytxt_url_env_override(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://host.docker.internal:9921")
    assert bridge_tools.anytxt_search_url() == "http://host.docker.internal:9921"


def test_persist_anytxt_url_records_last_known_good(tmp_path, monkeypatch) -> None:
    config_path = tmp_path / "bridge-search.config.json"
    config_path.write_text(json.dumps({"service": {"anytxt_url": "http://127.0.0.1:9920"}}), encoding="utf-8")
    monkeypatch.setenv("BRIDGE_SEARCH_CONFIG", str(config_path))
    bridge_config.get_bridge_config(reload=True)

    persisted = bridge_config.persist_anytxt_url("http://172.27.96.1:9921", source="health", probe_query="healthcheck")
    assert persisted == "http://172.27.96.1:9921"

    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["service"]["anytxt_url"] == "http://172.27.96.1:9921"
    assert data["service"]["last_known_good_anytxt_url"] == "http://172.27.96.1:9921"
    assert data["service"]["last_known_good_anytxt_url_source"] == "health"
    assert data["service"]["last_known_good_anytxt_probe_query"] == "healthcheck"
    assert data["_meta"]["anytxt_runtime"]["last_known_good_url"] == "http://172.27.96.1:9921"

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
    monkeypatch.setattr(
        search_backends,
        "resolve_path",
        lambda path, env: "/mnt/d/Docs/" + path.split("\\")[-1] if env == "wsl" else path,
    )
    result = bridge_tools.system_locator("txt", target_env="windows", limit=2, offset=5)
    command_text = _command_text(seen["cmd"])
    assert "-viewport-offset" in command_text
    assert "-viewport-count" in command_text
    assert result["meta"]["everything_native_paging"] is True
    assert result["meta"]["has_more"] is True
    assert result["meta"]["total_found_exact"] is False
    assert result["meta"]["total_found"] == 7
    assert result["meta"]["returned_count"] == 2
    assert len(result["results"]) == 2


def test_system_locator_everywhere_disables_native_paging_for_consistent_merge(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "resolve_es_exe", lambda: "/mnt/c/Program Files/Everything/es.exe")
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name in ("everything", "wsl_find"))
    monkeypatch.setattr(search_backends, "everything_supports_native_paging", lambda: True)
    monkeypatch.setattr(search_backends, "path_allowed_for_search_result", lambda path: True)
    seen = {}

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        seen["cmd"] = cmd
        if text:
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout=b"D:\\Docs\\one.txt\n", stderr=b"")

    monkeypatch.setattr(search_backends.subprocess, "run", fake_run)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: "/mnt/d/Docs/one.txt" if env == "wsl" else path)
    result = bridge_tools.system_locator("txt", target_env="everywhere", limit=2, offset=0)
    command_text = _command_text(seen["cmd"])
    assert "-viewport-offset" not in command_text
    assert "-viewport-count" not in command_text
    assert result["meta"]["everything_native_paging"] is False


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
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9920")

    class FakeResponse:
        status = 200

        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    seen = {}

    def fake_urlopen(req, timeout=5):
        payload = json.loads(req.data.decode("utf-8"))
        seen.setdefault("methods", []).append(payload["method"])
        body = json.dumps({"result": {"output": {"files": [{"path": r"C:\Users\david\memo.txt", "snippet": "needle here"}]}}}).encode("utf-8")
        return FakeResponse(body)

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: "/mnt/c/Users/david/memo.txt" if path == r"C:\Users\david\memo.txt" and env == "wsl" else path)
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert seen["methods"] == ["ATRpcServer.Searcher.V1.GetResult"]
    assert result["results"][0]["path"] == "/mnt/c/Users/david/memo.txt"


def test_content_locator_anytxt_hydrates_missing_snippets_via_fragments(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9920")

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    seen = []

    def fake_urlopen(req, timeout=5):
        payload = json.loads(req.data.decode("utf-8"))
        seen.append(payload["method"])
        if payload["method"] == "ATRpcServer.Searcher.V1.GetResult":
            body = json.dumps({"result": {"output": {"files": [{"path": r"C:\Users\david\memo.txt", "fid": "9223736511748752040", "snippet": ""}]}}}).encode("utf-8")
        elif payload["method"] == "ATRpcServer.Searcher.V1.GetFragment":
            body = json.dumps({"result": {"output": {"fragment": ""}}}).encode("utf-8")
        else:
            body = json.dumps({"result": {"output": {"fragments": [{"fragment": "needle here"}]}}}).encode("utf-8")
        return FakeResponse(body)

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: "/mnt/c/Users/david/memo.txt" if path == r"C:\Users\david\memo.txt" and env == "wsl" else path)
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert seen == ["ATRpcServer.Searcher.V1.GetResult", "ATRpcServer.Searcher.V1.GetFragment", "ATRpcServer.Searcher.V1.GetFragmentAll"]
    assert result["results"][0]["snippet"] == "needle here"


def test_anytxt_search_count_uses_json_rpc_search_method(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9920")
    seen = {}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body
            self.headers = {"content-type": "application/json", "Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    def fake_urlopen(req, timeout=5):
        payload = json.loads(req.data.decode("utf-8"))
        seen["method"] = payload["method"]
        return FakeResponse(json.dumps({"result": {"count": 12}}).encode("utf-8"))

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    count = search_backends._query_anytxt_search_count("http://winhost:9920", "needle", max_bytes=1000)
    assert seen["method"] == "ATRpcServer.Searcher.V1.Search"
    assert count == 12


def test_anytxt_ocr_uses_json_rpc_ocr_method(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9920")
    seen = {}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body
            self.headers = {"content-type": "application/json", "Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    def fake_urlopen(req, timeout=5):
        payload = json.loads(req.data.decode("utf-8"))
        seen["method"] = payload["method"]
        assert payload["params"]["input"]["file"] == r"C:\Users\david\image.png"
        return FakeResponse(json.dumps({"result": {"output": {"text": "scanned text"}}}).encode("utf-8"))

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: r"C:\Users\david\image.png")
    result = bridge_tools.anytxt_ocr(r"/mnt/c/Users/david/image.png")
    assert seen["method"] == "ATRpcServer.Searcher.V1.OCR"
    assert result["success"] is True
    assert result["results"][0]["text"] == "scanned text"
    assert result["results"][0]["raw_path"] == "/mnt/c/Users/david/image.png"
    assert result["meta"]["anytxt_url_used"] == "http://winhost:9920"


def test_anytxt_sync_index_uses_json_rpc_syncindex_method(monkeypatch) -> None:
    monkeypatch.setenv("BRIDGE_SEARCH_ANYTXT_URL", "http://winhost:9920")
    seen = {}

    class FakeResponse:
        def __init__(self, body: bytes):
            self._body = body
            self.headers = {"content-type": "application/json", "Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    def fake_urlopen(req, timeout=5):
        payload = json.loads(req.data.decode("utf-8"))
        seen["method"] = payload["method"]
        assert payload["params"]["input"]["folder"] == r"C:\Users\david\Documents"
        return FakeResponse(json.dumps({"result": {"output": {"message": "indexed"}}}).encode("utf-8"))

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(search_backends, "resolve_path", lambda path, env: r"C:\Users\david\Documents")
    result = bridge_tools.anytxt_sync_index(r"/mnt/c/Users/david/Documents")
    assert seen["method"] == "ATRpcServer.Searcher.V1.SyncIndex"
    assert result["success"] is True
    assert result["results"][0]["raw_path"] == "/mnt/c/Users/david/Documents"
    assert result["results"][0]["response"]["result"]["output"]["message"] == "indexed"
    assert result["meta"]["anytxt_url_used"] == "http://winhost:9920"


def test_server_anytxt_ocr_tool_delegates(monkeypatch) -> None:
    seen = {}
    bridge_server = _load_server_module_with_fake_mcp(monkeypatch)

    def fake_anytxt_ocr(file_path: str):
        seen["file_path"] = file_path
        return {"success": True, "results": [{"type": "ocr_result", "text": "ok"}], "errors": [], "warnings": [], "meta": {}}

    monkeypatch.setattr(bridge_server, "bridge_anytxt_ocr", fake_anytxt_ocr)
    result = bridge_server.anytxt_ocr(r"C:\Users\david\image.png")
    assert seen["file_path"] == r"C:\Users\david\image.png"
    assert result["results"][0]["text"] == "ok"


def test_server_anytxt_sync_index_tool_delegates(monkeypatch) -> None:
    seen = {}
    bridge_server = _load_server_module_with_fake_mcp(monkeypatch)

    def fake_anytxt_sync_index(folder: str):
        seen["folder"] = folder
        return {"success": True, "results": [{"type": "sync_index_result", "message": "ok"}], "errors": [], "warnings": [], "meta": {}}

    monkeypatch.setattr(bridge_server, "bridge_anytxt_sync_index", fake_anytxt_sync_index)
    result = bridge_server.anytxt_sync_index(r"C:\Users\david\Documents")
    assert seen["folder"] == r"C:\Users\david\Documents"
    assert result["results"][0]["message"] == "ok"


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


def test_integration_like_anytxt_html_ui_is_incompatible(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")
    class FakeResponse:
        status = 200
        headers = {"content-type": "text/html; charset=UTF-8"}
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, _max_bytes): return b"<!DOCTYPE html><html><title>Anytxt Searcher</title>"
    monkeypatch.setattr(search_backends.urllib.request, "urlopen", lambda req, timeout=5: FakeResponse())
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert result["success"] is False
    assert result["errors"][0]["code"] == "anytxt_incompatible_endpoint"


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
    config_path = setup_skill._write_runtime_config(str(repo_root), "http://winhost:9920")
    payload = (repo_root / "config" / "bridge-search.config.json").read_text(encoding="utf-8")
    assert config_path.endswith("bridge-search.config.json")
    assert '"anytxt_url": "http://winhost:9920"' in payload


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


# --- Phase 10 new tests ---


def test_resolve_path_does_not_cache_failures(monkeypatch) -> None:
    """When wslpath fails transiently, resolve_path should retry on next call."""
    call_count = 0

    def fake_run(cmd, capture_output=False, text=False, check=False, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise OSError("transient failure")
        return SimpleNamespace(returncode=0, stdout="/mnt/d/test\n", stderr="")

    monkeypatch.setattr(path_policy.subprocess, "run", fake_run)
    path_policy._RESOLVE_CACHE.clear()

    r1 = path_policy.resolve_path(r"D:\test", "wsl")
    assert r1 == r"D:\test"

    r2 = path_policy.resolve_path(r"D:\test", "wsl")
    assert r2 == "/mnt/d/test"
    assert call_count == 2


def test_is_binary_file_null_byte(tmp_path) -> None:
    binary = tmp_path / "bin.dat"
    binary.write_bytes(b"hello\x00world")
    assert file_ops.is_binary_file(str(binary)) is True


def test_is_binary_file_valid_utf8(tmp_path) -> None:
    text = tmp_path / "text.txt"
    text.write_text("hello world", encoding="utf-8")
    assert file_ops.is_binary_file(str(text)) is False


def test_is_binary_file_utf16_bom(tmp_path) -> None:
    utf16 = tmp_path / "utf16.txt"
    utf16.write_text("hello", encoding="utf-16")
    assert file_ops.is_binary_file(str(utf16)) is False


def test_read_text_with_fallbacks_truncation(monkeypatch, tmp_path) -> None:
    target = tmp_path / "big.txt"
    target.write_text("x" * 200, encoding="utf-8")
    monkeypatch.setattr(bridge_config, "get_bridge_config", lambda reload=False: {
        **bridge_config._DEFAULTS,
        "limits": {**bridge_config._DEFAULTS["limits"], "max_read_bytes": 50},
    })
    result = bridge_tools.hybrid_file_io("read", str(target))
    assert result["success"] is True
    assert len(result["results"][0]["content"]) == 50
    assert any(w["code"] == "read_truncated" for w in result["warnings"])


def test_manage_file_copy_same_path_blocked(tmp_path) -> None:
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")
    result = bridge_tools.hybrid_file_io("copy", str(src), destination_path=str(src))
    assert result["success"] is False
    assert result["errors"][0]["code"] == "same_path"


def test_manage_file_move_same_path_blocked(tmp_path) -> None:
    src = tmp_path / "file.txt"
    src.write_text("data", encoding="utf-8")
    result = bridge_tools.hybrid_file_io("move", str(src), destination_path=str(src))
    assert result["success"] is False
    assert result["errors"][0]["code"] == "same_path"


def test_manage_file_copy_into_self_blocked(tmp_path) -> None:
    src = tmp_path / "parent"
    src.mkdir()
    (src / "child.txt").write_text("data", encoding="utf-8")
    dst = src / "subdir"
    result = bridge_tools.hybrid_file_io("copy", str(src), destination_path=str(dst))
    assert result["success"] is False
    assert result["errors"][0]["code"] == "recursive_destination"


def test_wsl_find_root_uses_home_by_default(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "_wsl_locator_full_root_allowed", lambda: False)
    import os
    assert search_backends._wsl_filename_find_root() == os.path.expanduser("~")


def test_wsl_find_root_uses_slash_when_allowed(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "_wsl_locator_full_root_allowed", lambda: True)
    assert search_backends._wsl_filename_find_root() == "/"


def test_empty_content_write_warns(tmp_path) -> None:
    target = tmp_path / "empty.txt"
    result = bridge_tools.hybrid_file_io("write", str(target), content=None, is_confirmed=True)
    assert result["success"] is True
    assert any(w["code"] == "empty_content_write" for w in result["warnings"])


def test_empty_string_content_write_warns(tmp_path) -> None:
    target = tmp_path / "empty2.txt"
    result = bridge_tools.hybrid_file_io("write", str(target), content="", is_confirmed=True)
    assert result["success"] is True
    assert any(w["code"] == "empty_content_write" for w in result["warnings"])


def test_meta_degraded_flag_set_on_partial_success() -> None:
    from bridge_search.result_models import success_response, make_issue
    resp = success_response(
        results=[{"type": "hit", "path": "/tmp/a"}],
        errors=[make_issue(code="backend_error", message="boom")],
    )
    assert resp["success"] is True
    assert resp["meta"]["degraded"] is True


def test_meta_degraded_flag_not_set_on_clean_success() -> None:
    from bridge_search.result_models import success_response
    resp = success_response(results=[{"type": "hit"}], errors=[])
    assert "degraded" not in resp["meta"]


def test_anytxt_unexpected_structure_returns_invalid_response(monkeypatch) -> None:
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "anytxt")

    class FakeResponse:
        status = 200
        def __enter__(self): return self
        def __exit__(self, exc_type, exc, tb): return False
        def read(self, _max_bytes): return b'{"unexpected": "shape"}'

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", lambda req, timeout=5: FakeResponse())
    result = bridge_tools.content_locator("needle", target_env="windows")
    assert result["success"] is False
    assert any(e["code"] == "invalid_response" for e in result["errors"])


def test_anytxt_wt_live_bootstrap_controls_are_parseable() -> None:
    fixture = Path(__file__).parent / "fixtures" / "anytxt_wt" / "live_bootstrap.js"
    text_input, select_name, search_signal, drive_options = search_backends._extract_anytxt_wt_controls(
        fixture.read_text(encoding="utf-8")
    )
    assert text_input
    assert select_name
    assert search_signal
    assert drive_options == [("", "All Files")]


def test_anytxt_wt_default_drive_option_suppresses_redundant_specific_options() -> None:
    drive_options = [("", "All Files"), ("C:", "C:"), ("D:", "D:")]
    assert search_backends._effective_anytxt_wt_drive_options(drive_options) == [("", "All Files")]


def test_anytxt_wt_driver_queries_default_drive_option_once(monkeypatch) -> None:
    def mock_load(*args, **kwargs):
        raise search_backends.AnyTxtEndpointError("html")
    monkeypatch.setattr(search_backends, "_load_anytxt_json_response", mock_load)
    monkeypatch.setattr(search_backends, "_extract_anytxt_wt_controls", lambda _html: ("q", "drive", "search", [("", "All Files"), ("C:", "C:")]))
    monkeypatch.setattr(search_backends, "_extract_anytxt_wt_search_button_id", lambda _html: None)
    monkeypatch.setattr(search_backends, "_extract_anytxt_wt_ack", lambda _html: "1")
    monkeypatch.setattr(search_backends, "_extract_anytxt_wt_page_id", lambda _html: "1")
    monkeypatch.setattr(
        search_backends,
        "_extract_anytxt_wt_results",
        lambda _html: [{"type": "content_hit", "path": "C:/note.txt", "snippet": "needle"}],
    )

    requests = []

    class FakeResponse:
        status = 200
        headers = {"content-type": "text/html; charset=UTF-8"}

        def __init__(self, body: bytes):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    def fake_urlopen(req, timeout=5):
        requests.append(req)
        if len(requests) == 1:
            return FakeResponse(b'<html><a href="?wtd=abc">session</a></html>')
        if len(requests) == 2:
            return FakeResponse(b"bootstrap")
        return FakeResponse(b"results")

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)

    hits = search_backends._query_anytxt_hits("http://127.0.0.1:9921", "needle", limit=10, offset=0, max_bytes=100_000)

    assert len(hits) == 1
    search_posts = [req for req in requests if getattr(req, "data", None) and b"request=jsupdate" in req.data]
    assert len(search_posts) == 1
    assert b"drive=&" in search_posts[0].data


def test_anytxt_wt_no_files_response_is_clean_zero_hits() -> None:
    fixture = Path(__file__).parent / "fixtures" / "anytxt_wt" / "live_vat201_no_files_response.js"
    assert search_backends._extract_anytxt_wt_results(fixture.read_text(encoding="utf-8")) == []


def test_anytxt_wt_driver_returns_zero_hits_for_live_no_files_flow(monkeypatch) -> None:
    fixture_dir = Path(__file__).parent / "fixtures" / "anytxt_wt"
    root_html = (fixture_dir / "live_root.html").read_text(encoding="utf-8")
    bootstrap_js = (fixture_dir / "live_bootstrap.js").read_text(encoding="utf-8")
    no_files_js = (fixture_dir / "live_vat201_no_files_response.js").read_text(encoding="utf-8")
    responses = iter(
        [
            (b"<!DOCTYPE html><html></html>", "text/html; charset=UTF-8"),
            (root_html.encode("utf-8"), "text/html; charset=UTF-8"),
            (bootstrap_js.encode("utf-8"), "text/javascript; charset=UTF-8"),
            (no_files_js.encode("utf-8"), "text/javascript; charset=UTF-8"),
        ]
    )

    class FakeResponse:
        status = 200

        def __init__(self, body: bytes, content_type: str):
            self._body = body
            self.headers = {"content-type": content_type, "Content-Type": content_type}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, _max_bytes):
            return self._body

    def fake_urlopen(req, timeout=5):
        body, content_type = next(responses)
        return FakeResponse(body, content_type)

    monkeypatch.setattr(search_backends.urllib.request, "urlopen", fake_urlopen)
    hits = search_backends._query_anytxt_hits(
        "http://172.22.192.1:9921",
        "VAT201",
        limit=3,
        offset=0,
        max_bytes=500_000,
    )
    assert hits == []


def test_escape_find_glob_escapes_brackets() -> None:
    assert search_backends._escape_find_glob("test[0]") == r"test\[0\]"
    assert search_backends._escape_find_glob(r"test\file") == r"test\\file"
    assert search_backends._escape_find_glob("normal") == "normal"


def test_wsl_locate_database_refreshes_once_daily(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("hello", encoding="utf-8")
    db_path = tmp_path / "wsl-locate.db"
    now = {"value": 1_700_000_000.0}

    monkeypatch.setattr(search_backends.time, "time", lambda: now["value"])
    search_backends._build_wsl_locate_db(str(db_path), str(root))
    assert search_backends._wsl_locate_db_is_stale(str(db_path), str(root)) is False

    now["value"] += 60 * 60
    assert search_backends._wsl_locate_db_is_stale(str(db_path), str(root)) is False

    now["value"] += (24 * 60 * 60) + 1
    assert search_backends._wsl_locate_db_is_stale(str(db_path), str(root)) is True


def test_wsl_locate_stale_db_serves_results_when_refresh_fails(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("hello", encoding="utf-8")
    db_path = tmp_path / "wsl-locate.db"
    db_path.write_text(
        f"# generated_at=1000 root={root}\n{note}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BRIDGE_SEARCH_LOCATE_DB_PATH", str(db_path))
    monkeypatch.setattr(search_backends, "_wsl_locate_db_is_stale", lambda db, search_root, max_age_seconds=86400.0: True)
    scheduled = {"value": False}

    def mock_schedule(db, root):
        scheduled["value"] = True
        with search_backends._WSL_LOCATE_REFRESH_LOCK:
            search_backends._WSL_LOCATE_REFRESH_IN_FLIGHT.add(db)
        return True

    monkeypatch.setattr(
        search_backends,
        "_schedule_wsl_locate_refresh",
        mock_schedule,
    )

    results, errors, warnings, truncated, refresh_scheduled = search_backends._wsl_locate_search("note", str(root), False, 10)
    assert truncated is False
    assert errors == []
    assert refresh_scheduled is True
    assert scheduled["value"] is True
    assert len(results) == 1
    assert results[0]["path"] == str(note)
    assert any(w["code"] == "backend_unavailable" for w in warnings)


def test_system_locator_sets_refresh_scheduled_meta_when_wsl_locate_stale(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("hello", encoding="utf-8")
    db_path = tmp_path / "wsl-locate.db"
    db_path.write_text(
        f"# generated_at=1000 root={root}\n{note}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BRIDGE_SEARCH_LOCATE_DB_PATH", str(db_path))
    monkeypatch.setattr(search_backends, "_wsl_locate_db_is_stale", lambda db, search_root, max_age_seconds=86400.0: True)
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "wsl_locate")
    monkeypatch.setattr(search_backends, "_wsl_filename_find_root", lambda: str(root))

    def mock_schedule(db, root):
        with search_backends._WSL_LOCATE_REFRESH_LOCK:
            search_backends._WSL_LOCATE_REFRESH_IN_FLIGHT.add(db)
        return True

    monkeypatch.setattr(search_backends, "_schedule_wsl_locate_refresh", mock_schedule)

    response = bridge_tools.system_locator("note", target_env="wsl")
    assert response["success"] is True
    assert response["meta"]["wsl_locate_refresh_scheduled"] is True


def test_system_locator_sets_refresh_scheduled_meta_false_when_wsl_locate_fresh(monkeypatch, tmp_path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    note = root / "note.txt"
    note.write_text("hello", encoding="utf-8")
    db_path = tmp_path / "wsl-locate.db"
    db_path.write_text(
        f"# generated_at=2000 root={root}\n{note}\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("BRIDGE_SEARCH_LOCATE_DB_PATH", str(db_path))
    monkeypatch.setattr(search_backends, "_wsl_locate_db_is_stale", lambda db, search_root, max_age_seconds=86400.0: False)
    monkeypatch.setattr(search_backends, "backend_enabled", lambda name: name == "wsl_locate")
    monkeypatch.setattr(search_backends, "_wsl_filename_find_root", lambda: str(root))

    response = bridge_tools.system_locator("note", target_env="wsl")
    assert response["success"] is True
    assert response["meta"]["wsl_locate_refresh_scheduled"] is False
