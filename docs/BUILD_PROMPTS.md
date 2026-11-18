# Build prompts for Claude Code

Paste one prompt per milestone, in order. After each one: do the "You check" steps yourself,
then move on. If a check fails, tell Claude Code exactly what you saw and ask it to fix it
before continuing.

Start a fresh Claude Code session for each milestone (type `/clear`, or quit and run `claude`
again). The spec and CLAUDE.md carry the context, so nothing is lost.

---

## Milestone 0: Repo and scaffold

```
Read CLAUDE.md and SPEC.md in this folder in full before doing anything.

Then do Milestone 0 from the spec:
1. Move SPEC.md and BUILD_PROMPTS.md into docs/.
2. Initialise git, add a .gitignore suited to Python + Node, and create .env.example.
3. Scaffold the backend (FastAPI, health endpoint) and frontend (React + Vite + TypeScript +
   Tailwind + shadcn/ui, placeholder home page) following the layout in the spec.
4. Add the Makefile so `make dev` runs both, and `make test` runs the tests.
5. Write docs/PROCESS_MAP.md: the six-stage pipeline as a Mermaid flowchart with every decision
   point, plus a short plain-English description of each stage.
6. Create docs/PROGRESS.md and docs/ASSUMPTIONS.md.
7. Add the GitHub Actions CI workflow.
8. Create a private GitHub repo called invoice-to-decision with the gh CLI and push. If gh is
   not installed or not logged in, stop and tell me the exact commands to run.
9. Fill in the Commands section of CLAUDE.md.

Before you start, check which of these are installed and tell me what is missing: python 3.12,
uv, node, npm, git, gh. Commit in small logical steps. Finish with a plain-English summary and
the exact steps for me to see it running.
```

You check: `make dev` opens a page in the browser; the repo exists on GitHub; the CI run is green.

---

## Milestone 1: Data and test invoices

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 1.

Build the database models, the seed CSVs and seeded history exactly as in SPEC section 4, the
seed and reset logic, and scripts/generate_invoices.py producing all 13 test invoices plus the
2 seeded-history invoices, with data/invoices/expected.json as the answer key.

Requirements:
- Every number in section 4.4 must appear on the PDFs exactly as specified. Recompute each
  subtotal, tax and total yourself and tell me if any figure in the spec is inconsistent.
- Four visually distinct layouts. Scanned cases must have no extractable text; verify this with
  a script and show me the output.
- Open each generated PDF as an image and look at it. Fix anything that looks unrealistic,
  clipped or unreadable. For case 10, confirm the invoice number is absent and the total is
  genuinely unreadable.
- Commit the generated PDFs.

Finish with a table of the 15 files and what each contains, and tell me how to open them.
```

You check: open all 15 PDFs and read them. Do they look like invoices from four different
companies? Is case 10's total truly hidden?

---

## Milestone 2: Decision logic

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 2.

Implement the Validate, Match, Rules and Decide stages as pure, typed Python functions with the
findings structure from section 3.1, driven by config/rules.yaml. No API calls and no web code
in this milestone.

Write the unit tests and the answer-key test from section 8 (items 1 and 2), feeding the
ground-truth extractions from expected.json through the stages. All 13 cases and all 3
sequences must produce the expected decision, match type and finding codes.

If a case cannot produce its expected outcome under the rules as written, do not bend the rule
or the test to make it pass. Stop and explain the conflict to me.

Finish by showing me the test output, and for cases 1, 5, 8, 9 and 10 print the full decision
(headline, reasons, owner, next action) so I can read the wording.
```

You check: read the five printed decisions aloud. Would a finance manager understand each one
without help? If not, ask for the wording to be improved.

---

## Milestone 3: Extraction

Before this milestone: create an Anthropic API key in the Claude Console, add a few dollars of
credit, and put it in a file named `.env` in the project folder as `ANTHROPIC_API_KEY=...`.
Never paste the key into the chat.

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 3. My API key is in .env.

First read the current Anthropic documentation for PDF input and for structured output, and
tell me in two or three sentences which approach you will use and why.

Implement the Receive and Extract stages per sections 3.2 and 3.3, including page rendering,
hashing, saved extractions, retry, the fallback mode and the daily cap.

Then build scripts/eval_extraction.py (`make eval`): run live extraction over all 15 PDFs,
compare every field with expected.json, and write docs/EXTRACTION_EVAL.md with per-field
accuracy and a list of every mismatch. Report the real results. If a field is wrong, improve
the prompt or schema, re-run, and record both the before and after numbers.

Pay particular attention to case 10: invoice_number and total must come back null. If the model
guesses either, that is the most important thing to fix.

Finally run the end-to-end check: real extraction feeding the decision logic for all 13 cases.
Show me the results table. Tell me roughly what the evaluation cost in API usage.
```

You check: read docs/EXTRACTION_EVAL.md. You will be asked about accuracy in the interview;
these are your real numbers.

---

## Milestone 4: Pipeline and API

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 4.

Implement the run orchestration (section 5.1), all API endpoints (5.2), the state updates on
approval, human review resolution (3.8), and demo reset with auto-seed on startup (5.3).

Write API integration tests with extraction mocked, covering: a full run polled to completion,
the PO balance changing after an approval, resolving a REVIEW run, the three sequence cases,
reset restoring the seed state, and a run that fails cleanly when extraction raises an error.

Then demonstrate it for real: start the server, submit sample 1 and sample 5 with curl against
the live extraction, and show me the JSON of the finished runs and the stage timings.
```

You check: nothing visual yet. Confirm the tests pass and the two curl runs show APPROVE and
REVIEW.

---

## Milestone 5: Web app

```
Read CLAUDE.md and docs/SPEC.md, especially section 6. Do Milestone 5.

Build all five screens against the real API. The run view is the centrepiece: it must show each
stage as it executes with its real duration, and work both live and as a record opened later.

Design matters here; this UI is graded and will be screen-shared in an interview. Before
coding, tell me the visual direction you are taking in a few sentences (type, colour, density).
Then build it. Use real data throughout, no placeholder content.

When done, run the app, open it in a browser yourself, and take screenshots of: the dashboard
with history, a run in progress, a finished APPROVE run, the REVIEW run for case 5 showing the
PO balance, case 8 showing the earlier invoice side by side, case 9 showing the suggested PO,
and case 10 showing the missing fields. Look at each screenshot critically and fix what is
weak. Then run all 13 samples through the UI after a reset and confirm each decision matches
expected.json.
```

You check: run cases 1, 4, 5, 8, 9, 10 yourself in the browser. Click Reset and do it again.
Note anything confusing and ask for changes in plain words ("the reason text is too small",
"I can't tell which stage is running").

---

## Milestone 6: Hardening

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 6.

1. Go through every screen and make sure loading, empty and error states exist and read well.
   Try to break it: upload a non-PDF, a 20 MB file, a blank PDF, a photo of a cat saved as PDF,
   and submit two runs at once. Fix what breaks.
2. Temporarily set an invalid API key and confirm a run fails cleanly with a readable message,
   and that a sample with a saved extraction falls back and is clearly labelled.
3. Add the Playwright smoke test.
4. Write README.md (what it is, how it works in one diagram, how to run it locally, how to run
   tests, known limits from SPEC section 12).
5. Complete docs/ASSUMPTIONS.md with every assumption made about the business problem, in
   plain English.
6. Review the whole codebase once for dead code, unclear names and missing comments on the
   non-obvious parts, and tidy it.

Update docs/PROGRESS.md honestly: implemented, tested or verified for every feature.
```

You check: read ASSUMPTIONS.md and PROGRESS.md. These are your interview notes.

---

## Milestone 7: Deploy and demo prep

```
Read CLAUDE.md and docs/SPEC.md. Do Milestone 7.

1. Write the Dockerfile (builds the frontend, serves everything from FastAPI) and confirm the
   container runs locally.
2. Recommend a host for a single Docker web service that gives a public HTTPS URL. Check the
   current plans and documentation of two or three options, and tell me the trade-offs: cost,
   whether the service sleeps when idle, whether the disk persists. I want no cold-start delay
   when an interviewer opens the link. Wait for my choice.
3. Walk me through the deployment step by step, including setting ANTHROPIC_API_KEY and the
   other env vars on the host. Tell me exactly what to click or run.
4. Once live, run the smoke test against the public URL and run all 13 samples there.
5. Write docs/DEMO_SCRIPT.md: a 5-minute script for the video (happy path, then cases 5, 8 and
   10, with what to say at each stage) and a longer interview version covering cases 1, 4, 5,
   8, 9 and 10 in order, starting from a reset. Include a pre-demo checklist and what to do if
   the AI service is slow or down.
```

You check: open the public link on your phone and on another network. Run the demo script
start to finish twice without touching the code.
