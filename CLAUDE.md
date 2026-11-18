# Invoice-to-Decision

A web app that takes a vendor invoice PDF, reads it, checks it against purchase orders and
company rules, and produces an explained decision: approve, send to a human, or reject. Built as
a take-home case study that will be demoed live.

**The full specification is `docs/SPEC.md`. Read it before doing any work in a new session.**

## How to work in this repo

- Build one milestone at a time (SPEC section 10). Do not start the next until asked.
- Decisions marked FIXED in the spec are settled. If you believe one is wrong, stop and say why
  before changing anything.
- Where the spec is silent, make a sensible engineering choice and record it in
  `docs/ASSUMPTIONS.md` in one line.
- The owner is new to building software and must explain this in an interview. Prefer simple,
  readable code. After each milestone, give a short plain-English summary of what you built and
  why, and how to see it working.

## Rules that must never be broken

1. The AI model is used only in the Extract stage. Every check and the decision are
   deterministic code.
2. Money is `Decimal`, never float.
3. No fake delays, mock stages or simulated results in the running app.
4. Never claim something works without running it. Never invent a metric. Track status in
   `docs/PROGRESS.md` as implemented / tested / verified.
5. Never commit `.env` or any secret. The API key stays server-side.
6. Check current official documentation before using the Anthropic SDK or deploying to a host;
   do not rely on memory for API details.

## Git

- Conventional commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`), small and logical.
- Run the tests before every commit. Push at the end of each milestone.
- Work on `main`; this is a solo project.

## Commands

Run from the repo root. Needs Python 3.12, uv, Node and npm.

| Command | What it does |
|---|---|
| `make install` | Install backend (`uv sync`) and frontend (`npm install`) dependencies |
| `make dev` | Run backend (http://localhost:8000) and frontend (http://localhost:5173) together; Ctrl+C stops both |
| `make test` | Backend tests (pytest), then frontend type-check and build |
| `make lint` | `ruff` on the backend, `oxlint` on the frontend |
| `make build` | Production build of the frontend into `frontend/dist` |
| `make backend` / `make frontend` | Run just one of the two servers |
| `make seed` | Reset the database (`var/app.db`) to the seed data and print the PO balances |
| `make invoices` | Regenerate the 15 invoice PDFs, `expected.json` and `seed_invoices.json` from `scripts/invoice_definitions.json` (needs Playwright's Chromium; installs it if missing) |
| `make check-invoices` | Recompute every invoice figure and check each PDF's text layer (scans must have none) |
| `make decisions` | Run the answer key's ground-truth extractions through the decision logic and print one line per case; `make decisions CASES="1 5 8"` prints those decisions in full. No AI model, no saved database |

Not built yet (added in a later milestone): `make eval`.

Useful one-offs:

- One backend test: `cd backend && uv run pytest tests/test_health.py -q`
- The answer-key test only: `cd backend && uv run pytest tests/test_answer_key.py -v`
- Add a backend dependency: `cd backend && uv add <package>` (dev-only: `uv add --dev <package>`)
- Add a shadcn/ui component: `cd frontend && npx shadcn@latest add <component>`
- Health check: `curl http://localhost:8000/api/health`
- Reset demo data on a running server: `curl -X POST http://localhost:8000/api/demo/reset`
- CI status: `gh run list --limit 3`
