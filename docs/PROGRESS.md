# Progress

Status of every feature, kept honest (SPEC section 8).

- **implemented**: the code exists.
- **tested**: an automated test passes.
- **verified**: seen working end to end by actually running it.

A feature not listed here has not been started.

## Milestone 0: Repo and scaffold

| Feature | Status | Evidence |
|---|---|---|
| Backend health endpoint `GET /api/health` | tested + verified | `backend/tests/test_health.py` passes; `curl localhost:8000/api/health` returned `{"status":"ok"}` |
| Frontend placeholder home page | verified | `npm run build` succeeds; page served on port 5173 |
| Frontend reaches backend through the dev proxy | verified | `curl localhost:5173/api/health` returned `{"status":"ok"}` while `make dev` was running |
| `make dev` runs both servers | verified | Both ports answered from one `make dev` |
| `make test` | verified | 1 backend test passed, frontend build succeeded |
| CI workflow (backend tests + frontend build) | see below | |
| Process map | implemented | `docs/PROCESS_MAP.md` |

The placeholder page's appearance in a real browser has not been checked by the implementer;
only that it builds and is served.

## Known issues

- pytest prints one deprecation warning from Starlette's test client (it suggests the `httpx2`
  package instead of `httpx`). Harmless; tests pass.

## Milestones 1 to 7

Not started.
