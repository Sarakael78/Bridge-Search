# AnyTXT path-prefix proxy pattern

Use this when AnyTXT is reachable on a fixed HTTP listener but you want a public path such as `https://x.gqb.bar/anytxt` instead of exposing the service at the root.

Observed workable pattern:
- Upstream service: `http://BDE.goby-halfbeak.ts.net:9921`
- Local proxy listener: `http://127.0.0.1:9922/anytxt`
- Public route: `https://x.gqb.bar/anytxt`

Implementation notes:
- Put a small local reverse proxy in front of AnyTXT that strips the `/anytxt` prefix before forwarding requests upstream.
- Rewrite upstream `Location` headers back under `/anytxt` so redirects stay on the mounted path.
- Add a Cloudflare Tunnel ingress rule for the mounted path, not the upstream root.
- If the route should be private, create a separate Cloudflare Access application for the same path prefix, rather than relying on the tunnel alone.

Verification checklist:
- `curl http://127.0.0.1:<proxy-port>/anytxt` returns the AnyTXT UI or API response.
- `curl -I https://<public-host>/anytxt` returns the expected Access challenge or app response.
- The tunnel config places the mounted-path ingress rule before broader catch-alls.
- The Access app `self_hosted_domains` includes the mounted path wildcard, e.g. `x.gqb.bar/anytxt*`.

Pitfalls:
- A 200 on the AnyTXT root page only proves the service is reachable; it does not prove the bridge can actually use the endpoint for content search.
- AnyTXT may expose an HTML search UI rather than a JSON API; treat the service as HTTP-only and probe the live search surface before assuming a static API shape.
- If the upstream app is path-sensitive, do not point Cloudflare straight at it without the local prefix-stripping proxy.
