# AnyTXT endpoint runtime discovery

Session note: the AnyTXT HTTP service is not a fixed static host:port. Treat it as a runtime-discovered service and persist the last verified endpoint back into bridge config whenever a probe or content search succeeds.

Observed working pattern:
- The endpoint can move when WSL recreates its Hyper-V adapter. Probe the live WSL default gateway (`ip route show default`) rather than trusting a stale private-network value.
- A typical WSL gateway endpoint looks like `http://<wsl-default-gateway>:9921`.
- If `/etc/resolv.conf` is owned by Tailscale (`100.100.100.100`), it is not the Windows host gateway; use the default route gateway or `Get-NetIPConfiguration` for `vEthernet (WSL (Hyper-V firewall))`.
- Config keys used by the bridge:
  - `service.anytxt_url`
  - `service.last_known_good_anytxt_url`
  - `service.last_known_good_anytxt_url_updated_at`
  - `service.last_known_good_anytxt_url_source`
  - `service.last_known_good_anytxt_probe_query`
  - `_meta.anytxt_runtime.last_known_good_url`
  - `_meta.anytxt_runtime.last_verified_at`
  - `_meta.anytxt_runtime.last_verified_source`
  - `_meta.anytxt_runtime.last_probe_query`

Operational rule:
- If `get_health` or a real AnyTXT content search succeeds, write the endpoint back into config immediately as the last-known-good URL.
- When the URL changes, treat the persisted value as the first recovery target, not the only source of truth.
- Do not rely on memory or a stale docs sample port; probe the live service and refresh config.
- Standalone rediscovery command: `python3 scripts/rediscover_anytxt_endpoint.py`.
- By default it performs a lightweight UI/session probe and persists the endpoint if the live search surface is parseable; add `--verify-search` to also run a content-search verification query.
- Use `--query` and `--fallback-query` to control the verification searches, and `--json` when you want machine-readable output for chaining.
- If the helper reports `HttpSearch=0`, the HTTP Search Service is disabled in `C:\ProgramData\Anytxt\config\config.db`; enable it in the AnyTXT app before rediscovery can succeed.

Failure interpretation:
- HTTP 200 on the root page only means the service is reachable.
- A reachable page that does not expose the expected search form/probe path should be treated as an incompatible endpoint for bridge content search, not as “service down”.
- Prefer the live bridge health/content code path to discover and record the endpoint.
