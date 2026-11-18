// The dashboard's one filter system. Runs are filtered by where they stand now (their
// state), and each summary tile points at one of these filters.

import type { RunState, RunSummary } from './api'

export type Filter = 'ALL' | 'APPROVED' | 'AWAITING' | 'REJECTED'

// Which states each filter shows. Runs that failed or are still in progress have no
// outcome yet, so they appear only under "All".
const STATES: Record<Exclude<Filter, 'ALL'>, RunState[]> = {
  APPROVED: ['approved', 'approved_by_reviewer'],
  AWAITING: ['awaiting_review'],
  REJECTED: ['rejected', 'rejected_by_reviewer'],
}

export const FILTERS: { key: Filter; label: string; empty: string }[] = [
  { key: 'ALL', label: 'All', empty: 'No invoices have been run yet.' },
  { key: 'APPROVED', label: 'Approved', empty: 'Nothing has been approved yet.' },
  { key: 'AWAITING', label: 'Awaiting review', empty: 'Nothing is waiting for review.' },
  { key: 'REJECTED', label: 'Rejected', empty: 'Nothing has been rejected.' },
]

export function runsFor(filter: Filter, runs: RunSummary[]): RunSummary[] {
  if (filter === 'ALL') return runs
  return runs.filter((run) => STATES[filter].includes(run.state))
}
