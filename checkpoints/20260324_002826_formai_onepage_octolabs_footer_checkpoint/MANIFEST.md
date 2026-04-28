# FormAI Checkpoint

- Timestamp: 2026-03-24 00:28:26 Europe/Istanbul
- Branch: codex/formai-checkpoint-20260317
- Commit: a3ee34f8814dd87da71f3c60602f0912e4a30da5
- Tag: checkpoint/formai-onepage-octolabs-footer-20260324-002826

## Scope
- One-page marketing site refinement
- Product-specific before/after section
- North-style animated FAQ
- Footer simplified into a North-like closing section
- Anchor scrolling hardened for sticky header behavior
- API job metadata writes made atomic to avoid partial-read race conditions

## Validation
- Python tests: 93 tests OK
- Web build: next build OK

## Key Paths
- <project-root>/web/components/marketing-home.tsx
- <project-root>/web/components/site-chrome.tsx
- <project-root>/web/components/north-faq.tsx
- <project-root>/web/app/globals.css
- <project-root>/src/formai/api_jobs.py
