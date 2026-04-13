from __future__ import annotations

import subprocess
import urllib.error
import urllib.request
from typing import Any, Dict, List, Tuple

from . import config
from .search_backends import _get_effective_anytxt_urls, resolve_es_exe


def run_command_capture(cmd: List[str], timeout: float = 30) -> Tuple[int, str, str]:
    try:
        r = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return r.returncode, r.stdout or "", r.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, "", str(e)


def check_health() -> Dict[str, Any]:
    """Perform a comprehensive health check of all configured backends."""
    be = config.backend_enabled("everything")
    ba = config.backend_enabled("anytxt")
    bf = config.backend_enabled("wsl_find")
    bg = config.backend_enabled("wsl_grep")

    results: Dict[str, Any] = {
        "overall_success": True,
        "backends": {
            "everything": {"enabled": be},
            "anytxt": {"enabled": ba},
            "wsl_find": {"enabled": bf},
            "wsl_grep": {"enabled": bg},
        },
        "errors": [],
        "warnings": [],
    }

    if not any([be, ba, bf, bg]):
        results["overall_success"] = False
        results["errors"].append({
            "code": "no_backends_enabled",
            "message": "All search backends are disabled in config/env."
        })
        return results

    if be:
        es = resolve_es_exe()
        if not es:
            results["backends"]["everything"]["status"] = "error"
            results["backends"]["everything"]["message"] = "es.exe not found."
            results["errors"].append({
                "code": "everything_missing",
                "message": "Everything (es.exe) not found. Is it installed and on Windows PATH?"
            })
            results["overall_success"] = False
        else:
            code, out, err = run_command_capture([es, "-version"], timeout=10)
            if code != 0:
                results["backends"]["everything"]["status"] = "error"
                results["backends"]["everything"]["message"] = f"es.exe failed: {err or out}"
                results["errors"].append({
                    "code": "everything_service_error",
                    "message": "Everything CLI returned an error. Is the Everything service running?"
                })
                results["overall_success"] = False
            else:
                results["backends"]["everything"]["status"] = "ok"
                results["backends"]["everything"]["version"] = out.strip()

    if ba:
        urls = _get_effective_anytxt_urls()
        anytxt_reachable = False
        probed_urls = []
        for url in urls:
            # Probe the actual search endpoint so health matches runtime behavior.
            sep = "&" if "?" in url else "?"
            probe_url = f"{url}{sep}q=healthcheck"
            probed_urls.append(probe_url)
            try:
                with urllib.request.urlopen(probe_url, timeout=5) as resp:  # nosec B310 (local operator-configured AnyTXT endpoint)
                    if resp.status == 200:
                        anytxt_reachable = True
                        results["backends"]["anytxt"]["url_working"] = probe_url
                        break
            except (urllib.error.URLError, OSError, TimeoutError, ValueError):
                continue
        
        if not anytxt_reachable:
            results["backends"]["anytxt"]["status"] = "error"
            results["backends"]["anytxt"]["probed_urls"] = probed_urls
            results["errors"].append({
                "code": "anytxt_unreachable",
                "message": f"AnyTXT HTTP service not reachable at configured URLs: {probed_urls}"
            })
            results["overall_success"] = False
        else:
            results["backends"]["anytxt"]["status"] = "ok"

    # WSL backends are usually 'ok' if the server is running, but we can verify presence
    if bf:
        if subprocess.run(["which", "find"], capture_output=True).returncode == 0:
            results["backends"]["wsl_find"]["status"] = "ok"
        else:
            results["backends"]["wsl_find"]["status"] = "error"
            results["overall_success"] = False

    if bg:
        if subprocess.run(["which", "grep"], capture_output=True).returncode == 0:
            results["backends"]["wsl_grep"]["status"] = "ok"
        else:
            results["backends"]["wsl_grep"]["status"] = "error"
            results["overall_success"] = False

    return results
