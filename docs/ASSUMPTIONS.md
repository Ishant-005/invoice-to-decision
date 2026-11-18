# Assumptions

Choices made where the spec is silent, one line each. Decisions the spec marks FIXED are not
repeated here.

## Milestone 0

- uv was not installed, so it was installed with Homebrew (`brew install uv`).
- In development the frontend runs on port 5173 and the backend on port 8000; Vite forwards `/api` requests to the backend, so the browser only ever talks to one address.
- All backend routes live under `/api`, leaving `/` free for the built frontend later.
- Frontend uses whatever `npm create vite@latest` and `shadcn@latest init` currently produce: Tailwind v4 (no `tailwind.config.js`), shadcn "nova" preset on Radix, oxlint as the linter.
- `make test` runs the backend tests and a frontend type-check + build; the frontend has no unit tests of its own yet.
- Makefile targets `seed`, `invoices` and `eval` are added in the milestone that builds them, rather than existing as empty stubs now.
- CI uses Python 3.12 and Node 24 (the versions used locally).
- Runtime files (database, uploads, page images) will live in a git-ignored `var/` folder.
