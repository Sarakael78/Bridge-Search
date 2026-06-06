# AnyTXT HTTP API notes

Session note for the WSL bridge update.

## Key points
- AnyTXT content search is HTTP-only in this workflow.
- On WSL2, the live service may be the Wt HTML search UI on the current Windows-host gateway, not a shell binary or a hard-coded `/search` endpoint. The gateway IP can change after WSL/Hyper-V networking changes; use runtime discovery/default-route probing rather than assuming a fixed IP. Older forum/API snippets may mention `9920`.
- The live page uses per-session form controls and a tokenised `wtd` page flow. The bridge should fetch the session page, extract the current hidden fields and submit controls, then post the search through the HTML form when a JSON endpoint is unavailable.
- A reachable root page is not enough; the bridge must complete a real search using the service’s exposed search surface.
- If the endpoint returns HTML without the expected form, 404, or an incompatible JSON shape, treat it as reachable-but-not-bridge-compatible and report `anytxt_incompatible_endpoint`.

- The bridge now drives the current Wt HTML/JavaScript surface by fetching the root page, loading the `request=script` bootstrap with the session `wtd`/`sid`, parsing the search input/select/button signal from the generated markup, and POSTing a `request=jsupdate` search event. The older `?wtd=<token>&js=no` path can return only a skeletal shell on this host.
- A `No files were found` Wt message is a compatible zero-hit response, not an endpoint failure.

## Operational lesson
- When documenting or troubleshooting content search, separate filename search (Everything / `es.exe`) from content search (AnyTXT HTTP UI/service).
- Do not use Windows filename-search success as proof that document-content search is working.
