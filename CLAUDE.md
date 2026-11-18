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

(Fill this section in during Milestone 0 and keep it current.)
