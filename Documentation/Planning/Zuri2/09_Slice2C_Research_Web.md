# Slice 2C — Research department and web tools

Status: **implemented 2026-11-10 — awaiting user confirmation**
Depends on: Slice 2B.

## What was added

- `http_get` tool:
  - public http/https only, ports 80/443,
  - blocks localhost, private, link-local, reserved addresses and URL
    credentials,
  - manual redirect validation (max 5),
  - 2 MB read cap, 20s timeout, bounded text,
  - GET only, no cookies/auth/custom headers.
- `browse_page` tool:
  - headless Chrome (caller-supplied system Chrome/Edge or autodetect),
  - validates the start and final URL,
  - Playwright request routing blocks non-public subresources,
  - returns title, visible text and links,
  - no clicks, forms, downloads, auth, cookies or screenshots.
- Seeded `research` agent: list/read/write/http_get/browse_page.
- Engineering agent gets http_get/browse_page for docs.
- HR can grant web tools for research roles.
- Settings: `ZURI_NETWORK_ENABLED`, `ZURI_BROWSER_EXECUTABLE`.
- Tests: URL/SSRF policy, disabled network, empty URL, agent grants, plus
  optional live HTTP and headless-browser tests (`ZURI_LIVE_TESTS=1`).

## Live proof

- `http_get https://example.com` → 200, text, 577 bytes.
- `browse_page https://example.com` → title `Example Domain`, non-empty text,
  200.
- Research task `t_fdb0277e6079`: fetched example.com via http_get, wrote
  `work/example.md` with title + URL; verifier 4/4; ~$0.005344; mind updated.
- 98 tests collected; 96 pass + 2 opt-in live tests; all 98 pass with
  `ZURI_LIVE_TESTS=1`.

## Security

- SSRF filtering is address/port based; DNS rebinding is not fully prevented.
- Browser HTTP(S) subresources are filtered, but page JavaScript runs and the
  browser is not an OS sandbox; WebSocket/WebRTC behavior is outside the filter.
- Web content is untrusted and may contain prompt injection; the verifier
  remains the success boundary, but use trusted sources.
- No auth, cookies, forms or POST.

## Limits

- No screenshots, form interaction, authenticated pages, JavaScript API
  automation or search-engine tool.
- Research/Engineering web access is public-only.
