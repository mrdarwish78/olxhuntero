# PROJECT MAP — Egyptian Used Phone Market Hunter

## [TECH_STACK]

| Component | Version | Role |
|-----------|---------|------|
| Python | 3.12 | Runtime |
| cloudscraper | 1.2.71 | Cloudflare bypass |
| beautifulsoup4 | 4.15.0 | HTML parsing |
| google-genai | 2.9.0 | Gemini AI (Search Grounding) |
| requests | 2.32+ | Telegram alerts |
| GitHub Actions | ubuntu-24.04 | Cron scheduler + execution |

## [SYSTEM_FLOW]

```
GitHub Actions Cron Trigger
  │
  ├─ 1. scrape_listings()       → cloudscraper GET → raw HTML
  ├─ 2. parse_listings()        → BeautifulSoup → list of ads
  ├─ 3. is_within_target_window() → filter by time mode (hourly/bulk)
  ├─ 4. filter_new_ads()        → dedup against processed_ids.txt
  ├─ 5. evaluate_with_gemini()  → Search Grounding → JSON classification
  ├─ 6. send_telegram()         → if "لقطة" found → POST to Telegram API
  └─ 7. git_push()              → commit updated state files
```

## [ARCHITECTURE]

**File layout:**
```
/Egyptian-Phone-Hunter
├── .github/workflows/scraper.yml    # CI/CD pipeline
├── main.py                           # Single-file orchestrator (20 functions)
├── requirements.txt                  # Pinned dependencies
├── processed_ids.txt                 # Dedup memory (ad IDs, one per line)
├── market_database.csv               # AI evaluation history
├── system_logs.csv                   # Operational logs
└── PROJECT_MAP.md                    # This file
```

**Function map (main.py):**

| Function | Lines | Role |
|----------|-------|------|
| `log()` | 33-46 | CSV appender — INFO/WARN/ERROR |
| `scrape_listings()` | 48-75 | cloudscraper GET + 3x retry |
| `_text()` | 78-79 | bs4 text extraction helper |
| `_extract_price_value()` | 81-83 | parse "EGP 15,000" → 15000 |
| `_parse_relative_minutes()` | 85-99 | "3 hours ago" → 180 minutes |
| `_extract_ad_id()` | 101-103 | regex ID from /en/ad/...-ID123.html |
| `_build_ad_id()` | 105-110 | ID with MD5 fallback |
| `_parse_via_classes()` | 112-146 | class-based parser (primary) |
| `_parse_via_structure()` | 148-190 | structure-based parser (fallback 1) |
| `_parse_via_regex()` | 192-214 | regex parser (fallback 2) |
| `parse_listings()` | 216-231 | Hybrid 3-level parser orchestrator |
| `is_within_target_window()` | 233-240 | Time filter: 60min (hourly) / 240min (bulk) |
| `load_processed_ids()` / `filter_new_ads()` | 242-280 | Dedup against `processed_ids.txt` |
| `evaluate_with_gemini()` | 282-320 | Prompt → Gemini 2.5 Flash + Search Grounding → JSON |
| `send_telegram()` | 322-345 | POST to Telegram Bot API with inline keyboard |
| `format_alert()` | 347-366 | Build HTML message (no URL in body) |
| `save_processed_ids()` / `append_market_db()` | 372-438 | Append state to CSV/TXT |
| `git_push()` | 409-437 | Subprocess commit+push |
| `main()` | 439-493 | Orchestrator — all steps wired together |

## [KEY CHANGES SINCE V1]

| Change | Date | Rationale |
|--------|------|-----------|
| `google-generativeai` → `google-genai==2.9.0` | 2026-06-23 | Deprecated package replaced |
| `gemini-2.0-flash` → `gemini-2.5-flash` | 2026-06-23 | User request |
| MD5 ID fallback | 2026-06-23 | Ads missing `-ID\d+` pattern in URL |
| Unicode stdout fix | 2026-06-23 | Windows cp1252 console encoding |
| URL from `<article>` parent (not `<div._23f16658>`) | 2026-06-26 | Dubizzle moved `<a>` out of card div into `<article>` |
| Inline Keyboard for ad link | 2026-06-26 | "يلا نشوف" button replaces plain-text `<a>` in message body |

| market_database.csv 17-column schema | ✅ Implemented | NEW_DB_HEADER, HYPERLINK, session_type, issue_reason, separator row, auto-migration |

| 17-column CSV schema with HYPERLINK + session_type | 2026-06-26 | issue_reason, auto-migration, separator row between cycles |

## [ORPHANS & PENDING]

| Item | Status | Notes |
|------|--------|-------|
| HTML parsing on live dubizzle | ✅ Verified — CSS classes work | 45 ads parsed via `_23f16658` class |
| Gemini Search Grounding with `gemini-2.5-flash` | ✅ Verified | 17 ads evaluated successfully; deals detected and alerted |
| Telegram alerting with inline keyboard | ✅ Verified | Payload structure confirmed; button "يلا نشوف" links to ad |
| ID extraction with MD5 fallback | ✅ Verified | Works for all 45 ads; URL-based IDs when available |
| `market_database.csv` population | ✅ Verified | 34 rows populated with classifications |
| Git push | ❌ Only fails locally | Not a git repo on Windows; works on GitHub Actions `ubuntu-24.04` |
