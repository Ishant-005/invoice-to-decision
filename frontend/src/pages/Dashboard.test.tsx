// The dashboard has one filter system. These tests check that a tile's count, the count on
// the filter it switches to, and the number of rows then shown all agree, before and after
// a reviewer approves one REVIEW run and rejects another.
//
// The page is rendered for real; only the two API calls are answered from the data below.
// (That the server's own totals agree with its runs list is tested in the backend:
// test_the_dashboard_tiles_agree_with_the_runs_listed_under_each_filter.)

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, expect, test, vi } from 'vitest'

import type { RunState, RunSummary, Stats } from '@/lib/api'

import { Dashboard } from './Dashboard'

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

function run(id: string, state: RunState): RunSummary {
  const decision =
    state === 'approved' ? 'APPROVE' : state === 'rejected' ? 'REJECT' : state === 'failed' || state === 'processing' ? null : 'REVIEW'
  return {
    id, state, decision,
    created_at: '2026-11-18T10:00:00Z', finished_at: '2026-11-18T10:00:05Z',
    file_name: `${id}.pdf`, source: 'sample',
    status: state === 'failed' ? 'failed' : state === 'processing' ? 'running' : 'completed',
    headline: decision ? 'Needs review: an example reason.' : null,
    owner: null, owner_label: null, vendor_id: 'V-001', vendor_name: `Vendor ${id}`,
    invoice_number: `INV-${id}`, invoice_date: '2026-11-05',
    pretax_amount: '100000.00', gross_amount: '118000.00', po_id: 'PO-2231',
    failed_stage: state === 'failed' ? 'receive' : null,
    error_message: state === 'failed' ? 'Only PDF files are accepted.' : null,
    resolution: null,
  }
}

/** The totals the server would send for these runs (the same definitions as the backend). */
function statsFor(runs: RunSummary[]): Stats {
  const count = (...states: RunState[]) => runs.filter((r) => states.includes(r.state)).length
  const processed = runs.length - count('failed', 'processing')
  return {
    total_runs: runs.length, processed,
    approved: count('approved', 'approved_by_reviewer'), auto_approved: count('approved'),
    auto_approved_percent: processed ? Math.round((1000 * count('approved')) / processed) / 10 : null,
    approved_by_reviewer: count('approved_by_reviewer'), awaiting_review: count('awaiting_review'),
    rejected: count('rejected', 'rejected_by_reviewer'), rejected_by_process: count('rejected'),
    rejected_by_reviewer: count('rejected_by_reviewer'), failed: count('failed'), in_progress: 0,
    value_approved_pretax: '200000.00', value_approved_gross: '236000.00', seeded_invoices: 2,
  }
}

async function showDashboard(runs: RunSummary[]) {
  const answers: Record<string, unknown> = {
    '/api/runs': { runs, seeded_history: [] },
    '/api/stats': statsFor(runs),
  }
  vi.stubGlobal('fetch', async (path: string) => new Response(JSON.stringify(answers[path])))
  const { container } = render(
    <MemoryRouter>
      <Dashboard />
    </MemoryRouter>,
  )
  await screen.findByText('Runs')
  await waitFor(() => expect(tileValue(container, 'Awaiting review')).not.toBe('…'))
  return container
}

const tile = (page: HTMLElement, label: string) => page.querySelector(`[data-tile="${label}"]`) as HTMLElement
const tileValue = (page: HTMLElement, label: string) => tile(page, label).querySelector('[data-value]')?.textContent
const chip = (page: HTMLElement, key: string) => page.querySelector(`[data-filter="${key}"]`) as HTMLElement
const chipCount = (page: HTMLElement, key: string) => Number(chip(page, key).querySelector('[data-count]')?.textContent)
const activeChip = (page: HTMLElement) => page.querySelector('[data-filter][aria-pressed="true"]')?.getAttribute('data-filter')
const rowsShown = (page: HTMLElement) => page.querySelectorAll('tbody tr').length

/** Click each tile and check: the right filter becomes active, and the tile's count, the
 *  filter's count and the rows shown are the same number. */
function expectTilesChipsAndRowsToAgree(page: HTMLElement, runs: RunSummary[]) {
  const stats = statsFor(runs)
  const cases: [tileLabel: string, filter: string, expected: number][] = [
    ['Invoices processed', 'ALL', stats.total_runs],
    ['Auto-approved', 'APPROVED', stats.approved],
    ['Awaiting review', 'AWAITING', stats.awaiting_review],
    ['Rejected', 'REJECTED', stats.rejected],
    ['Value approved', 'APPROVED', stats.approved],
  ]
  for (const [label, filter, expected] of cases) {
    fireEvent.click(tile(page, label))
    expect(activeChip(page), `${label} activates ${filter}`).toBe(filter)
    expect(chipCount(page, filter), `${label}: count on the filter`).toBe(expected)
    expect(rowsShown(page), `${label}: rows shown`).toBe(expected)
  }
  // The tiles that show a plain count show that same number.
  expect(tileValue(page, 'Invoices processed')).toBe(String(chipCount(page, 'ALL')))
  expect(tileValue(page, 'Awaiting review')).toBe(String(chipCount(page, 'AWAITING')))
  expect(tileValue(page, 'Rejected')).toBe(String(chipCount(page, 'REJECTED')))
  // "Value approved" is an amount; its subline gives the number of invoices it covers.
  expect(tile(page, 'Value approved').textContent).toContain(`${chipCount(page, 'APPROVED')} invoice`)
}

const BEFORE: RunSummary[] = [
  run('1', 'approved'), run('2', 'approved'), run('3', 'rejected'),
  run('4', 'awaiting_review'), run('5', 'awaiting_review'), run('6', 'awaiting_review'),
  run('7', 'failed'),
]
// A reviewer has approved run 4 and rejected run 5.
const AFTER: RunSummary[] = BEFORE.map((r) =>
  r.id === '4' ? run('4', 'approved_by_reviewer') : r.id === '5' ? run('5', 'rejected_by_reviewer') : r,
)

test('tile counts, filter counts and rows agree while reviews are waiting', async () => {
  const page = await showDashboard(BEFORE)
  expectTilesChipsAndRowsToAgree(page, BEFORE)
  expect(chipCount(page, 'APPROVED')).toBe(2)
  expect(chipCount(page, 'AWAITING')).toBe(3)
  expect(chipCount(page, 'REJECTED')).toBe(1)
})

test('they still agree after a reviewer approves one run and rejects another', async () => {
  const page = await showDashboard(AFTER)
  expectTilesChipsAndRowsToAgree(page, AFTER)
  expect(chipCount(page, 'APPROVED')).toBe(3)
  expect(chipCount(page, 'AWAITING')).toBe(1)
  expect(chipCount(page, 'REJECTED')).toBe(2)
  expect(tile(page, 'Rejected').textContent).toContain('1 by the process · 1 by a reviewer')
})

test('the State column says who settled each run; the Decision column keeps the verdict', async () => {
  const page = await showDashboard(AFTER)
  fireEvent.click(chip(page, 'ALL'))
  const text = page.querySelector('tbody')?.textContent ?? ''
  for (const label of ['Approved by the process', 'Approved by reviewer', 'Rejected by the process', 'Rejected by reviewer', 'Awaiting review'])
    expect(text).toContain(label)
  // Run 4 was sent for review by the process and then approved by a person.
  const row = [...page.querySelectorAll('tbody tr')].find((tr) => tr.textContent?.includes('INV-4'))
  expect(row?.textContent).toContain('Review')
  expect(row?.textContent).toContain('Approved by reviewer')
})

test('an empty filter says so in plain words', async () => {
  const page = await showDashboard([run('1', 'approved')])
  fireEvent.click(chip(page, 'AWAITING'))
  expect(page.textContent).toContain('Nothing is waiting for review.')
  fireEvent.click(chip(page, 'REJECTED'))
  expect(page.textContent).toContain('Nothing has been rejected.')
})
