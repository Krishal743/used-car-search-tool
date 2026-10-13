# Motorwise: approved MVP design

User approved implementation on 13 October 2026: React, FastAPI, SQLite, OLX first, Gemini free API preferred, Windows primary and Apple Silicon compatible. User reports OLX granted permission by email to scrape public car listings. Display photos; no image analysis.

## Components

- React dashboard: explicit search form, results with detail galleries/descriptions, assistant, shortlists, comparison, saved filters, history, manual listing entry, settings.
- FastAPI local server: validated requests, bounded cancellable search jobs, SQLite persistence, static frontend serving in production.
- OLX adapter: public category/search and listing pages; HTTP plus optional Playwright Chromium rendering; extract page state/JSON-LD or semantic HTML. Resolve city search URLs; enforce all filters locally. Unknown filtered fields are excluded by default with an explicit option to include them as unverified matches. No private endpoints, login automation, or stealth tooling.
- SQLite: saved search snapshots that can also accept explicitly imported or manually added cars, saved searches, separate shortlist snapshots, chat messages and cached assessments. No initial seed listings.
- AI: configurable Gemini model/key, scoped current-search or comparison context, description treated as untrusted seller claims, validated structured responses referring only to supplied listing IDs. Computation of asking-price comparables occurs in Python. No external browsing from chat, no image input, no background AI calls. A missing API key leaves search/compare usable and reports chat unavailable.

## Retrieval and failure handling

Search starts only via explicit POST. An ongoing user-started job is polled for progress; polling does not trigger new scraping. Bounded scan and detail budgets ensure broad searches finish. Display partial coverage, unmatched/excluded counts and errors; empty results must distinguish no matches from blocked/unreadable sources. Cancellation preserves collected matches. Jobs interrupted by restart become interrupted. Optional photo cache runs only within explicit retrieval, caps size/count, restricts hosts and redirects, and persists safe local image paths. Unsupported sources are clearly labeled planned/manual only.

## AI behavior

AI receives only captured listing fields, descriptions, calculated comparables and recent scoped conversation. It may rank differently according to user requests, identifies missing facts and questions for sellers, and distinguishes assumptions/claims. Validate referenced listing IDs and reject invented IDs. Pricing uses same normalized make/model, fuel/transmission, similar year and mileage, excludes the subject car, and requires at least three comparable listings. Never interpret asking price as sale price or infer mechanical condition from photos/descriptions.

## Runtime and verification

Backend binds localhost. Setup scripts install Python/Node dependencies, build React, and optionally install Chromium. Runtime needs Python; Node is needed only for setup/rebuild. Credentials stay in ignored environment configuration and backend memory. SQLite is under data/ with optional data directory override. No paid deployment or external hosting.

Verify extraction variants and blocked pages, filter validation/unknowns, cancellation/history, persistence, shortlist and scoped chat, AI validation/quota responses, image URL restrictions, API integration and frontend production build. Live OLX and Gemini are contingent on network access and an API key; report verification limits explicitly.
