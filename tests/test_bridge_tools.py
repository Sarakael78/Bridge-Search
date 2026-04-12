"""Unit tests for bridge logic (no WSL/Windows binaries required)."""

import copy
import os

import bridge_tools
from bridge_tools import _auto_target_env, _backend_enabled, _everything_search_arg, _clamp_int


def test_auto_target_env_windows_paths_use_wsl_branch() -> None:
    assert _auto_target_env(r"C:\Users\test") == "wsl"
    assert _auto_target_env("c:/temp/file.txt") == "wsl"


def test_auto_target_env_unix_paths_use_windows_branch() -> None:
    assert _auto_target_env("/mnt/c/Users") == "windows"
    assert _auto_target_env("/home/user/proj") == "windows"


def test_auto_target_env_relative_defaults_wsl() -> None:
    assert _auto_target_env("relative/path") == "wsl"


def test_everything_search_arg_partial_wraps() -> None:
    assert _everything_search_arg("foo", False) == "*foo*"
    assert _everything_search_arg("  bar  ", False) == "*bar*"


def test_everything_search_arg_respects_existing_globs() -> None:
    assert _everything_search_arg("a*b", False) == "a*b"
    assert _everything_search_arg("?x", False) == "?x"


def test_everything_search_arg_exact_unchanged() -> None:
    assert _everything_search_arg("readme.txt", True) == "readme.txt"


def test_clamp_int() -> None:
    assert _clamp_int(5, 0, 10) == 5
    assert _clamp_int(-1, 0, 10) == 0
    assert _clamp_int(99, 0, 10) == 10


def test_grep_line_file_path_parses_standard_grep() -> None:
    from bridge_tools import _grep_line_file_path

    assert _grep_line_file_path("/home/user/a.txt:12:hello") == "/home/user/a.txt"
    assert _grep_line_file_path(r"C:\temp\file.txt:3:content") == r"C:\temp\file.txt"


def test_grep_line_file_path_rejects_malformed() -> None:
    from bridge_tools import _grep_line_file_path

    assert _grep_line_file_path("no-colon-here") is None
    assert _grep_line_file_path("") is None


def test_backend_enabled_env_overrides_config(monkeypatch) -> None:
    monkeypatch.delenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", raising=False)
    cfg = copy.deepcopy(bridge_tools._DEFAULTS)
    cfg["backends"] = {**cfg["backends"], "everything": False}
    bridge_tools._cfg_cache = cfg
    try:
        monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "1")
        assert _backend_enabled("everything") is True
        monkeypatch.setenv("BRIDGE_SEARCH_ENABLE_EVERYTHING", "0")
        assert _backend_enabled("everything") is False
    finally:
        bridge_tools._cfg_cache = None


def test_config_paths_default_file(monkeypatch) -> None:
    monkeypatch.delenv("BRIDGE_SEARCH_CONFIG", raising=False)
    paths = bridge_tools._config_paths()
    assert len(paths) == 1
    assert paths[0].endswith(os.path.join("config", "bridge-search.config.json"))


def test_config_paths_env_override(monkeypatch, tmp_path) -> None:
    custom = tmp_path / "policy.json"
    custom.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("BRIDGE_SEARCH_CONFIG", str(custom))
    assert bridge_tools._config_paths() == [os.path.abspath(str(custom))]


def test_backend_enabled_reads_config_when_env_unset(monkeypatch) -> None:
    monkeypatch.delenv("BRIDGE_SEARCH_ENABLE_ANYTXT", raising=False)
    cfg = copy.deepcopy(bridge_tools._DEFAULTS)
    cfg["backends"] = {**cfg["backends"], "anytxt": False}
    bridge_tools._cfg_cache = cfg
    try:
        assert _backend_enabled("anytxt") is False
    finally:
        bridge_tools._cfg_cache = None
