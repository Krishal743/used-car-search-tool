# Motorwise

A personal, local used-car dashboard. Search public OLX car listings when you click **Search**, keep snapshots in SQLite, view available photos and seller descriptions, save cars, compare them, and ask Gemini questions about the captured results. The first version automatically searches **OLX only**. CarWale, Cars24, Spinny and Facebook Marketplace appear as unavailable sources with links; you can manually add cars from them.

This is an MVP. Live OLX retrieval and Gemini calls still need testing on a machine with working access to those services. See [Next steps](docs/NEXT_STEPS.md) for the current checklist and known blockers.

## Run on Windows

Install [Python 3.12+](https://www.python.org/downloads/), [Node.js 20.19+](https://nodejs.org/en/download) and a modern browser. From the project folder, double-click `scripts\setup_windows.cmd`, then `scripts\run_windows.cmd`. Keep the terminal window open while using the app. The dashboard opens at `http://127.0.0.1:8000`. Setup installs Chromium for pages that require browser rendering. It may download several hundred MB.

## Run on Linux

Install Python 3.12+ (including `venv`) and Node.js 20.19+, then from the project folder run:

```bash
./scripts/setup_linux.sh
./scripts/run_local.sh
```

The launcher prints and opens the dashboard address, starting at `http://127.0.0.1:8000`. If that port is busy, it tries ports 8001 through 8010. Keep the terminal running; press Ctrl+C to stop it. Setup downloads Playwright Chromium for OLX pages that require browser rendering. If the browser reports missing system libraries, run `.venv/bin/python -m playwright install --with-deps chromium` and then launch again.

If OLX is marked unavailable, first open `https://www.olx.in/bengaluru_g4058803/cars_c84` in your regular browser. Then check DNS and HTTPS from a terminal with `getent hosts www.olx.in` and `curl -IL --max-time 15 https://www.olx.in/bengaluru_g4058803/cars_c84`. A failed DNS or HTTPS check means the local app cannot fetch listings either. Restart the local server after changing its code or configuration, then retry Search and read the source status for the specific failure.

If curl reports certificate error 60, inspect the certificate issuer and verify that the system clock is correct. The Linux launcher uses Ubuntu's `/etc/ssl/certs/ca-certificates.crt` for HTTPX, so a trusted local CA installed in the system store is also used by the app. Only install a local CA supplied and verified by your network administrator; do not turn off HTTPS verification to make searches work.

On networks where a Sophos firewall inspects HTTPS traffic, the OLX certificate may be signed by a local `Sophos SSL CA`. Obtain the **signing CA certificate** from the network administrator or the managed Sophos portal, verify its fingerprint with the administrator, and install that CA in Ubuntu's trust store. The certificate shown for `*.olx.in` is a site certificate, not the signing CA. After installing the CA, confirm `curl -IL https://www.olx.in/bengaluru_g4058803/cars_c84` succeeds before restarting Motorwise. A different trusted network, such as a phone hotspot, is an alternative way to test immediately.

## Run on Apple Silicon/macOS

Install Python 3.12+ and Node.js 20.19+, then run:

```bash
chmod +x scripts/setup_macos.sh scripts/run_local.sh
./scripts/setup_macos.sh
./scripts/run_local.sh
```

## Gemini setup

Searching, saving, filtering and comparison work without an API key. For chat, create a Gemini API key in [Google AI Studio](https://aistudio.google.com/app/apikey). Enter it in the dashboard’s Settings page for the current app session, or copy `.env.example` to `.env` and set `GEMINI_API_KEY` for later launches. Keep the project on a free tier. The default `gemini-2.5-flash` currently has a free tier according to [Google’s pricing page](https://ai.google.dev/gemini-api/docs/pricing); limits and availability can change. Motorwise does not make paid fallback calls. On a 429 quota response it reports the failure while keeping your results. Free-tier API content may be used by Google to improve its products. Motorwise sends question text, listing specifications and descriptions to Gemini. It does not send pictures.

## How search works

1. Set filters and click **Search OLX cars**. This is the only action that starts a broad OLX retrieval job. Saved searches simply restore filters; chat uses saved results and never starts a search.
2. The app reads up to five OLX result pages and 120 listing details at a user-adjustable, bounded result limit (20 by default, maximum 60). It checks all filters locally. Missing filter fields exclude a car unless **Include cars with missing filter details** is on; included cars are marked unverified.
3. Detail pages supply the description and available photos. The app caches up to three photos per match locally when fetches succeed. If photos are absent or blocked, the card says so. Click a card for more photos, description, specifications and the original ad.
4. Results, past searches, shortlists and chats stay in `data/motorwise.sqlite3`; photos stay in `data/images/`. Stop the local server to back up the `data` directory. Search snapshots record their retrieval time; old listings may be sold or changed.
5. Add an individual public OLX link through **Add a car → Import OLX link**. Other site links can be manually recorded through **Enter manually**. Import explicitly reads only that link. A manual entry never pretends to be an automatically retrieved result.

Bengaluru is the configured OLX region. For another location, obtain its public OLX **Cars** search page in your browser, set the location name and paste that URL under **More filters**. The URL must be on `https://www.olx.in` and include `cars_c84`. The app reports a configuration error rather than silently searching Bengaluru. If OLX blocks access or changes its page structure, the search is marked unavailable or partial; the dashboard offers the original search link and manual entry. Chromium fallback uses public pages; the app does not log in or call private APIs.

Asking-price comparisons require at least three captured peer listings with the same make, model, fuel and transmission, years within two and similar mileage. Different variants are excluded when both variants are known. These are asking prices from the current snapshot, not a market valuation or sale prices. AI assessments treat seller descriptions as unverified claims and never inspect the images.

## Development and checks

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements.txt
npm --prefix frontend install --no-package-lock
npm --prefix frontend run build
.venv/bin/python -m pytest backend/tests
.venv/bin/python -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Use `npm --prefix frontend run dev` for a live frontend at `http://127.0.0.1:5173`; Vite proxies `/api` to FastAPI. The production build is served directly by FastAPI at port 8000. API documentation is at `http://127.0.0.1:8000/docs`.

## Current verification limit

This build environment has blocked direct DNS/network access to OLX and Gemini. Extraction and API behavior are tested with representative page-shaped fixtures and mocked HTTP requests, and the production frontend build is checked. **A successful live OLX scrape or Gemini call has not been verified here.** Run one broad Bengaluru search first and check the source status. If OLX renders a new page format or presents a challenge, the app shows a retrieval error and saved/manual workflows remain usable.
