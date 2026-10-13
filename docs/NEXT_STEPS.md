# Motorwise: next steps

Updated 13 October 2026. This is the local working checklist for the MVP. The app runs on Linux, but a successful live OLX search and Gemini response have not yet been verified.

## First: unblock and verify the MVP

- [ ] **Restore trusted HTTPS access to OLX.** On the current Linux network, `curl` fails certificate verification for OLX. The presented site certificate is issued by `Sophos SSL CA`, which indicates HTTPS inspection. Test on a phone hotspot, or obtain the network's signing CA from its administrator, verify its fingerprint independently, and install it in Ubuntu's trust store. Do not install the `*.olx.in` site certificate or disable TLS verification. Confirm `curl -IL https://www.olx.in/bengaluru_g4058803/cars_c84` succeeds.
- [ ] **Run a real Bengaluru OLX search.** Restart `./scripts/run_local.sh`, select broad filters, and click Search. Confirm the source is available, listings have correct prices and specifications, descriptions appear, and photos load. Compare several cards against their original ads. Update selectors and page handling if OLX has changed its markup. Keep search user-initiated and bounded.
- [ ] **Verify one detail import.** Use an individual public OLX listing URL and confirm its description, photo gallery, and URL are saved accurately.
- [ ] **Verify Gemini chat.** Supply a personal Gemini API key through Settings or `.env`, ask for a ranking and seller questions, and check that only captured listing facts are used. Confirm quota and error messages when the free tier is exhausted. Check current free-tier availability before relying on it.
- [ ] **Run checks on the target machine.** Execute `.venv/bin/python -m pytest backend/tests` and `npm --prefix frontend run build`. Investigate any test hang or failure reproduced outside the restricted build sandbox.

## Then: make the first release reliable

- [ ] **Review search coverage and accuracy.** Check whether the five-page and 120-detail cap finds enough cars for narrow filters. Measure rejected listings with missing fields and adjust the UI explanation or extraction, while keeping results clearly labeled as a sample.
- [ ] **Validate pricing and AI explanations.** Compare ranked results against their source ads. Confirm the app distinguishes seller claims from verified facts and avoids market-value claims when fewer than three suitable peer listings exist.
- [ ] **Test Windows and Apple Silicon.** Run each setup and launcher script, verify Playwright Chromium installation, and test search, photos, persistence, and chat. Record platform-specific fixes in the README.
- [ ] **Protect local data and credentials.** Keep `.env`, SQLite databases, cached images, and downloaded dependencies out of Git. Rotate any real Gemini key that was ever placed in a shared example file. Add a simple documented backup/restore procedure for `data/`.
- [ ] **Add another source only after OLX works well.** Check each platform's API or scraping permission and terms before automating it. Keep manual add and source-unavailable links for platforms that cannot be retrieved automatically.

## Current scope

Automatic search supports OLX public car pages only. Other platforms are manual links or entries. Searches run only when Search is clicked. The app stores search snapshots, shortlists, comparisons, and chat history locally in SQLite. It does not inspect images with AI; images are displayed and seller descriptions are included in the text assessment. These are asking prices and unverified seller statements.
