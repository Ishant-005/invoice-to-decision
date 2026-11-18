"""Runs one invoice through the six stages, in order, and records what each stage did.

    Receive -> Extract -> Validate -> Match -> Rules -> Decide

This is the only place that knows the order. Each stage is still a plain function; this
file calls them one after another, times each with a real clock, and writes a `StageEvent`
row when a stage starts and again when it finishes. The run view on the screen is drawn
from those rows, so what the user sees is what actually happened. There are no pauses or
made-up timings anywhere.

It runs in the background: `POST /api/runs` returns at once and the browser polls.

If anything goes wrong the run is marked `failed`, with the stage it happened in and a
readable message. A failed run never gets a decision and never touches a PO balance.
"""

import logging
import time
from typing import Any

from sqlalchemy import Engine
from sqlmodel import Session, select

from app import clock, config, db
from app.ledger import record_outcome
from app.models import Run, StageEvent, now_utc
from app.pipeline.decide import decide
from app.pipeline.extract import ExtractionError, extract
from app.pipeline.findings import Finding
from app.pipeline.match import match
from app.pipeline.receive import ReceiveError, receive
from app.pipeline.record import load_books
from app.pipeline.rules import apply_rules
from app.pipeline.validate import validate
from app.rules_config import default_rules

log = logging.getLogger("invoice.run")

STAGES = ("receive", "extract", "validate", "match", "rules", "decide")


class RunWiped(Exception):
    """The run was deleted by a demo reset while it was still in progress."""


def upload_path(run_id: str):
    """Where the PDF of a run is kept. Outside anything the web server serves."""
    return config.UPLOADS_DIR / f"{run_id}.pdf"


class StageRecorder:
    """Writes the StageEvent rows for one run and measures each stage's real duration."""

    def __init__(self, session: Session, run_id: str):
        self.session = session
        self.run_id = run_id
        self.event: StageEvent | None = None  # the row of the stage running now
        self.stage: str | None = None  # its name
        self.started = 0.0

    def run(self) -> Run:
        """The run's row, read fresh. Raises RunWiped if a reset has deleted it, so a run
        that was in flight during a reset can never write into the restored books."""
        run = self.session.exec(select(Run).where(Run.id == self.run_id)).first()
        if run is None:
            raise RunWiped()
        return run

    def start(self, stage: str) -> None:
        with db.STATE_LOCK:
            self.run()
            self.event = StageEvent(run_id=self.run_id, stage=stage, status="running")
            self.session.add(self.event)
            self.session.commit()
        self.stage = stage
        log.info("run=%s stage=%s status=running", self.run_id, stage)
        self.started = time.perf_counter()

    def elapsed_ms(self) -> float:
        return round((time.perf_counter() - self.started) * 1000, 1)

    def finish(self, result: dict[str, Any], findings: list[Finding] | None = None,
               commit: bool = True) -> None:
        duration = self.elapsed_ms()
        with db.STATE_LOCK:
            self.run()
            self.event.status = "done"
            self.event.duration_ms = duration
            self.event.result = result
            if findings is not None:
                self.event.findings = [f.model_dump(mode="json") for f in findings]
            self.session.add(self.event)
            if commit:
                self.session.commit()
        log.info("run=%s stage=%s status=done duration_ms=%s", self.run_id, self.stage,
                 duration)


def as_json(result, without: set[str] | None = None) -> dict[str, Any]:
    """A stage result as plain JSON. Amounts become text such as "180000.00", never floats."""
    return result.model_dump(mode="json", exclude=without)


def execute_run(run_id: str, db_engine: Engine | None = None) -> None:
    """Process one run from start to finish. Never raises: every outcome ends up in the
    database, where the run view reads it."""
    with Session(db_engine or db.engine) as session:
        recorder = StageRecorder(session, run_id)
        try:
            run_stages(session, recorder)
        except RunWiped:
            session.rollback()
            log.info("run=%s status=abandoned reason=demo_reset", run_id)
        except Exception as error:  # noqa: BLE001  (any failure must become a failed run)
            session.rollback()
            mark_failed(session, recorder, error)


def run_stages(session: Session, recorder: StageRecorder) -> None:
    run_id = recorder.run_id
    with db.STATE_LOCK:
        run = recorder.run()
        run.status = "running"
        file_name = run.file_name
        session.add(run)
        session.commit()

    # 1. Receive: check the file, fingerprint it, make the page images.
    recorder.start("receive")
    pdf_bytes = upload_path(run_id).read_bytes()
    received = receive(pdf_bytes, file_name, session, current_run_id=run_id)
    # The image paths are server folders; the API gives the browser URLs instead.
    recorder.finish(as_json(received, without={"page_images"}))

    # 2. Extract: the one stage that uses the AI model. It can take several seconds, so it
    #    runs outside the lock and other runs are not held up by it.
    recorder.start("extract")
    extracted = extract(pdf_bytes, received, session)
    recorder.finish(as_json(extracted))
    record = extracted.record

    # 3 to 6 are deterministic code and take milliseconds. They run under the lock, so
    # the PO balances and invoice history they read cannot change until this run has
    # recorded its own outcome.
    rules = default_rules()
    with db.STATE_LOCK:
        recorder.start("validate")
        validated = validate(record, clock.today(), rules.validate_)
        recorder.finish(as_json(validated, without={"findings"}), validated.findings)

        recorder.start("match")
        books = load_books(session)  # vendors, POs and earlier invoices, as they are now
        matched = match(record, validated, books, rules.match)
        recorder.finish(as_json(matched, without={"findings"}), matched.findings)

        recorder.start("rules")
        ruled = apply_rules(record, validated, matched, books, received.file_hash, rules.rules)
        recorder.finish(as_json(ruled, without={"findings"}), ruled.findings)

        # Decide, and record the outcome. One commit covers the decision, the invoice
        # joining the history and (for an APPROVE) the PO's billed-to-date.
        recorder.start("decide")
        decision = decide(validated, matched, ruled)
        run = recorder.run()
        record_outcome(session, run, record, validated, matched, decision)
        run.status = "completed"
        run.decision = decision.decision
        run.decision_detail = as_json(decision)
        run.finished_at = now_utc()
        session.add(run)
        recorder.finish(as_json(decision), commit=False)
        session.commit()

    log.info("run=%s status=completed decision=%s owner=%s", run_id, decision.decision,
             decision.owner)


def mark_failed(session: Session, recorder: StageRecorder, error: Exception) -> None:
    """Record a failure: which stage, and a message a person can read."""
    run_id = recorder.run_id
    stage = recorder.stage or STAGES[0]
    duration = recorder.elapsed_ms() if recorder.stage else None

    if isinstance(error, (ReceiveError, ExtractionError)):
        # These messages were written for the user (wrong file type, AI service down...).
        message = str(error)
        log.warning("run=%s stage=%s status=failed reason=%s", run_id, stage, message)
    else:
        # Anything else is a bug or an outage. Show a plain message, keep the detail in the log.
        message = (f"Something unexpected went wrong in the {stage.capitalize()} stage "
                   f"({type(error).__name__}). No decision was made. The details are in the "
                   "server log.")
        log.exception("run=%s stage=%s status=failed unexpected error", run_id, stage)

    try:
        with db.STATE_LOCK:
            run = session.exec(select(Run).where(Run.id == run_id)).first()
            if run is None:  # wiped by a reset in the meantime; nothing to record
                return
            event = recorder.event
            if event is not None and event.status == "running":
                event.status = "failed"
                event.duration_ms = duration
                session.add(event)
            run.status = "failed"
            run.failed_stage = stage
            run.error_message = message
            run.decision = None
            run.decision_detail = None
            run.finished_at = now_utc()
            session.add(run)
            session.commit()
    except Exception:
        session.rollback()
        log.exception("run=%s could not record the failure", run_id)


def fail_interrupted_runs(session: Session) -> int:
    """Called on startup. A run still `queued` or `running` belongs to a server process
    that has stopped, so it will never finish; mark it failed rather than leave the run
    view waiting for ever. Returns how many were marked."""
    stuck = session.exec(select(Run).where(Run.status.in_(("queued", "running")))).all()
    for run in stuck:
        running = session.exec(select(StageEvent).where(
            StageEvent.run_id == run.id, StageEvent.status == "running")).first()
        if running is not None:
            running.status = "failed"
            session.add(running)
        run.status = "failed"
        run.failed_stage = running.stage if running else None
        run.error_message = ("The server restarted while this invoice was being processed. "
                             "No decision was made. Please submit it again.")
        run.finished_at = now_utc()
        session.add(run)
        log.warning("run=%s status=failed reason=server_restarted", run.id)
    session.commit()
    return len(stuck)
