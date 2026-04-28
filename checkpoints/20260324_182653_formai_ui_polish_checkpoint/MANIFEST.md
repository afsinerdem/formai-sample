# FormAI UI Polish Checkpoint

- Timestamp: 2026-03-24 18:26:53 Europe/Istanbul
- Branch: codex/formai-checkpoint-20260317
- Commit: 585e7b0830b7d88ffbceaa0771ddb92a8e512ea7
- Tag: checkpoint/formai-ui-polish-20260324-182653

## Scope
- One-page marketing site refinements
- Reliable anchor scrolling with sticky header offset
- Mobile navigation and responsive layout improvements
- Footer simplified into a brand closing section
- Workbench proportion, spacing, and hierarchy polish
- Clean preview process reset to avoid stale CSS / high CPU from multiple Next servers

## Validation
- Web build: OK
- API smoke: 9 tests OK

## Key Files
- <project-root>/web/app/globals.css
- <project-root>/web/components/marketing-home.tsx
- <project-root>/web/components/site-chrome.tsx
- <project-root>/web/components/workbench.tsx
- <project-root>/web/components/job-detail.tsx
- <project-root>/web/components/hash-scroll-manager.tsx
- <project-root>/web/components/site-anchor-link.tsx
