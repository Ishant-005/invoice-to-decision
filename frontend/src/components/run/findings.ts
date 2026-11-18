// How a finding (the result of one check) is read: its look, its label, and summaries.

import { Check, Eye, Info, Minus, X } from 'lucide-react'

import type { Finding } from '@/lib/api'

export type Tone = 'pass' | 'note' | 'review' | 'reject' | 'skipped'

/** What a finding means for the decision, as one of five looks. */
export function toneOf(finding: Pick<Finding, 'status' | 'severity'>): Tone {
  if (finding.status === 'skipped') return 'skipped'
  if (finding.status === 'pass') return 'pass'
  if (finding.severity === 'reject') return 'reject'
  if (finding.severity === 'review') return 'review'
  return 'note' // a warning that does not stop an approval
}

export const TONES: Record<Tone, { label: string; icon: typeof Check; mark: string; text: string; wash: string }> = {
  pass: { label: 'Passed', icon: Check, mark: 'bg-approve-soft text-approve border-approve-line', text: 'text-approve', wash: '' },
  note: { label: 'Note', icon: Info, mark: 'bg-review-soft text-review border-review-line', text: 'text-review', wash: 'bg-review-soft/60' },
  review: { label: 'Needs review', icon: Eye, mark: 'bg-review-soft text-review border-review-line', text: 'text-review', wash: 'bg-review-soft' },
  reject: { label: 'Reject', icon: X, mark: 'bg-reject-soft text-reject border-reject-line', text: 'text-reject', wash: 'bg-reject-soft' },
  skipped: { label: 'Not checked', icon: Minus, mark: 'bg-muted text-muted-foreground border-border', text: 'text-muted-foreground', wash: '' },
}

/** "6 passed · 1 needs review · 1 note": the one-line summary of a stage's checks. */
export function summariseFindings(findings: Finding[]): string {
  const count = (tone: Tone) => findings.filter((finding) => toneOf(finding) === tone).length
  const parts = [
    count('reject') && `${count('reject')} reject`,
    count('review') && `${count('review')} needs review`,
    count('note') && `${count('note')} note${count('note') > 1 ? 's' : ''}`,
    count('pass') && `${count('pass')} passed`,
    count('skipped') && `${count('skipped')} not checked`,
  ].filter(Boolean)
  return parts.join(' · ')
}

/** The most serious look among a stage's findings; decides the colour of the summary. */
export function worstTone(findings: Finding[]): Tone {
  const tones = findings.map(toneOf)
  for (const tone of ['reject', 'review', 'note'] as const) if (tones.includes(tone)) return tone
  return 'pass'
}
