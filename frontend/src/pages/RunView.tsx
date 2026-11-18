// Screen 3: one run. The invoice page on the left, the six stages on the right, and the
// decision on top once it is made. The same screen follows a run live and shows it later
// as a record.

import { ArrowLeft, Loader2, TriangleAlert } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'

import { ErrorBox, Eyebrow, Loading, Panel, StateLabel, Tag } from '@/components/common'
import { DecisionBanner } from '@/components/run/DecisionBanner'
import { DuplicateCompare } from '@/components/run/DuplicateCompare'
import { STAGE_INFO } from '@/components/run/stages'
import { StageTimeline } from '@/components/run/StageTimeline'
import { SuggestedPO } from '@/components/run/SuggestedPO'
import { Button } from '@/components/ui/button'
import type { MatchResult, RulesResult, RunDetail, Stage } from '@/lib/api'
import { duration, moment } from '@/lib/format'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

const POLL_MS = 700 // how often a run in progress is fetched again
const REVEAL_MS = 450 // on a live run, how long each finished stage is given before the next

export function RunView() {
  const { runId } = useParams()
  // `key` gives each run its own fresh state when moving from one run to another.
  return <Run key={runId} runId={runId as string} />
}

function Run({ runId }: { runId: string }) {
  const isActive = (run: RunDetail) => run.status === 'queued' || run.status === 'running'
  const { data: run, error, loading, reload, setData } = useApi<RunDetail>(`/api/runs/${runId}`, isActive, POLL_MS)
  const { stages, settled, live } = usePacedStages(run)

  if (loading) return <Loading label="Loading the run…" />
  if (!run) return <ErrorBox message={error ?? 'The run could not be loaded.'} onRetry={reload} />

  const finished = (run.status === 'completed' || run.status === 'failed') && settled
  const match = stageResult<MatchResult>(run, 'match')
  const rules = stageResult<RulesResult>(run, 'rules')

  return (
    <>
      <RunHeader run={run} finished={finished} />

      {/* Top: the decision once made; until then, where the run has got to. */}
      {!finished ? (
        <Progress stages={stages} />
      ) : run.status === 'failed' ? (
        <FailedBanner run={run} />
      ) : (
        <div className="space-y-4">
          <DecisionBanner run={run} onResolved={setData} />
          {rules?.duplicates.map((link) => <DuplicateCompare key={link.file_name + link.kind} run={run} link={link} />)}
          {match && match.candidates.length > 0 && <SuggestedPO match={match} />}
        </div>
      )}

      <div className="mt-5 grid grid-cols-[minmax(0,5fr)_minmax(0,7fr)] items-start gap-5">
        <PagePreview run={run} />
        <div>
          <div className="mb-2.5 flex items-baseline justify-between pl-10">
            <h2 className="font-semibold">What happened, stage by stage</h2>
            {finished && run.total_duration_ms !== null && (
              <p className="text-xs text-muted-foreground">
                Total <span className="num font-medium text-foreground">{duration(run.total_duration_ms)}</span>, measured on the server
              </p>
            )}
          </div>
          <StageTimeline run={run} stages={stages} />
          {live && (
            <p className="mt-1 pl-10 text-xs text-muted-foreground">
              Stages 3 to 6 are ordinary code and finish within a few milliseconds of each other. This page shows them
              one at a time so they can be followed; every duration is the real one measured on the server.
            </p>
          )}
        </div>
      </div>
    </>
  )
}

function stageResult<T>(run: RunDetail, name: Stage['stage']): T | null {
  const stage = run.stages.find((candidate) => candidate.stage === name)
  return stage?.status === 'done' ? (stage.result as T) : null
}

/**
 * Decides how the six stages are shown right now.
 *
 * A run opened later as a record is shown exactly as stored. A run watched live is paced:
 * stages 3 to 6 finish within milliseconds of each other, so each finished stage is revealed
 * one after another (REVEAL_MS apart) rather than all at once. Nothing is invented: a stage
 * not yet revealed is shown as "waiting", and once revealed it shows its real result and its
 * real measured duration.
 */
function usePacedStages(run: RunDetail | null) {
  const [live, setLive] = useState(false) // true once this page has seen the run unfinished
  const [revealed, setRevealed] = useState(0) // how many finished stages have been revealed

  const active = run !== null && (run.status === 'queued' || run.status === 'running')
  const finishedStages = run ? run.stages.filter((stage) => stage.status === 'done' || stage.status === 'failed').length : 0

  if (active && !live) setLive(true)

  useEffect(() => {
    if (!live || revealed >= finishedStages) return
    const timer = window.setTimeout(() => setRevealed((count) => count + 1), REVEAL_MS)
    return () => window.clearTimeout(timer)
  }, [live, revealed, finishedStages])

  if (!run) return { stages: [] as Stage[], settled: false, live }
  if (!live) return { stages: run.stages, settled: true, live }

  const settled = revealed >= finishedStages
  const stages = run.stages.map((stage, index): Stage => {
    if (index < revealed) return stage // revealed: shown as it is
    if (index === revealed && stage.status === 'running') return stage // really running now
    if (settled && stage.status === 'not_run') return stage // a failure stopped the run before it
    // Finished on the server (or queued behind such a stage) but not yet revealed here.
    return { ...stage, status: 'waiting', duration_ms: null, result: null, findings: [] }
  })
  return { stages, settled, live }
}

// --- Header ----------------------------------------------------------------------------

function RunHeader({ run, finished }: { run: RunDetail; finished: boolean }) {
  return (
    <div className="mb-4 flex items-center gap-4">
      <Button asChild variant="outline" size="sm">
        <Link to="/">
          <ArrowLeft /> Dashboard
        </Link>
      </Button>
      <div className="min-w-0">
        <h1 className="truncate text-lg font-semibold tracking-tight">
          {finished && run.vendor_name ? (
            <>
              {run.vendor_name}
              <span className="num ml-2 font-medium text-muted-foreground">{run.invoice_number ?? 'no invoice number'}</span>
            </>
          ) : (
            run.file_name
          )}
        </h1>
      </div>
      <div className="ml-auto flex shrink-0 items-center gap-3 text-xs text-muted-foreground">
        <Tag>{run.source === 'sample' ? 'Sample invoice' : 'Uploaded'}</Tag>
        <span className="code">{run.file_name}</span>
        <span>Submitted {moment(run.created_at)}</span>
        <span className="text-[13px]">
          <StateLabel state={finished ? run.state : 'processing'} />
        </span>
      </div>
    </div>
  )
}

// --- While running ---------------------------------------------------------------------

function Progress({ stages }: { stages: Stage[] }) {
  const done = stages.filter((stage) => stage.status === 'done').length
  const current = stages.find((stage) => stage.status === 'running') ?? stages.find((stage) => stage.status === 'waiting')
  return (
    <Panel className="flex items-center gap-4 px-5 py-4" aria-live="polite">
      <Loader2 className="size-5 animate-spin text-primary" />
      <div className="flex-1">
        <p className="text-base font-semibold">
          Processing: stage {Math.min(done + 1, 6)} of 6{current && <>, {STAGE_INFO[current.stage].name}</>}
        </p>
        <p className="text-muted-foreground">
          {current ? STAGE_INFO[current.stage].does : 'Finishing'}. The decision appears here when all six stages are done.
        </p>
      </div>
      <div className="flex gap-1.5" aria-hidden>
        {stages.map((stage) => (
          <span
            key={stage.stage}
            className={cn(
              'h-1.5 w-9 rounded-full',
              stage.status === 'done' ? 'bg-primary' : stage.status === 'running' ? 'animate-pulse bg-primary/50' : 'bg-border',
            )}
          />
        ))}
      </div>
    </Panel>
  )
}

function FailedBanner({ run }: { run: RunDetail }) {
  return (
    <section className="flex items-start gap-3 rounded-lg border border-reject-line bg-reject-soft px-5 py-4">
      <TriangleAlert className="mt-0.5 size-5 shrink-0 text-reject" />
      <div className="flex-1">
        <Eyebrow className="text-reject">No decision</Eyebrow>
        <h2 className="mt-1 text-lg font-semibold">
          The run stopped{run.failed_stage && <> in the {STAGE_INFO[run.failed_stage].name} stage</>}
        </h2>
        <p className="mt-1 max-w-3xl leading-relaxed">{run.error_message}</p>
        <p className="mt-1 text-muted-foreground">
          A run that fails never produces a decision and never changes a purchase order balance.
        </p>
      </div>
      <Button asChild variant="outline">
        <Link to="/new">Submit another invoice</Link>
      </Button>
    </section>
  )
}

// --- The invoice page ------------------------------------------------------------------

function PagePreview({ run }: { run: RunDetail }) {
  const [page, setPage] = useState(0)
  return (
    <Panel className="sticky top-[72px] overflow-hidden">
      <div className="flex items-center justify-between border-b px-3.5 py-2">
        <h2 className="font-semibold">The invoice as received</h2>
        {run.pages.length > 1 ? (
          <div className="flex gap-1">
            {run.pages.map((_, index) => (
              <button
                key={index}
                type="button"
                onClick={() => setPage(index)}
                className={cn('num rounded px-2 py-0.5 text-xs', index === page ? 'bg-primary text-primary-foreground' : 'text-muted-foreground hover:bg-muted')}
              >
                Page {index + 1}
              </button>
            ))}
          </div>
        ) : (
          run.pages.length === 1 && (
            <a href={run.pages[0]} target="_blank" rel="noreferrer" className="text-xs text-muted-foreground underline-offset-2 hover:underline">
              Open at full size
            </a>
          )
        )}
      </div>
      {run.pages.length > 0 ? (
        <div className="max-h-[calc(100vh-130px)] overflow-y-auto bg-muted p-3">
          <img src={run.pages[page]} alt={`Page ${page + 1} of ${run.file_name}`} className="w-full rounded-sm border bg-white" />
        </div>
      ) : (
        <div className="flex aspect-[1/1.2] items-center justify-center bg-muted px-6 text-center text-muted-foreground">
          {run.status === 'failed' ? 'No page image: the file could not be opened as a PDF.' : 'The page appears once the file has been received.'}
        </div>
      )}
    </Panel>
  )
}
