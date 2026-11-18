// A list of findings (the results of checks) shown as a checklist. Used by the Validate,
// Match and Rules stages.

import type { Finding } from '@/lib/api'
import { cn } from '@/lib/utils'

import { type Tone, toneOf, TONES } from './findings'

const OWNERS: Record<string, string> = { ap: 'Accounts Payable', procurement: 'Procurement', vendor: 'Vendor' }

export function ToneMark({ tone, className }: { tone: Tone; className?: string }) {
  const { icon: Icon, mark } = TONES[tone]
  return (
    <span className={cn('flex size-[18px] shrink-0 items-center justify-center rounded-full border', mark, className)}>
      <Icon className="size-3" strokeWidth={2.5} />
    </span>
  )
}

export function Checklist({ findings }: { findings: Finding[] }) {
  return (
    <ul className="divide-y">
      {findings.map((finding) => {
        const tone = toneOf(finding)
        const flagged = tone === 'review' || tone === 'reject' || tone === 'note'
        return (
          <li key={finding.code + finding.message} className={cn('flex gap-2.5 py-2', flagged && '-mx-2 rounded-md px-2', flagged && TONES[tone].wash)}>
            <ToneMark tone={tone} className="mt-px" />
            <div className="min-w-0 flex-1">
              <p className={cn('leading-snug', tone === 'skipped' && 'text-muted-foreground', !flagged && 'text-foreground/80')}>
                {finding.message}
              </p>
              {/* A problem or a note says what it means and who owns it; a pass needs no more. */}
              {flagged && (
                <p className="mt-1 text-xs">
                  <span className={cn('font-semibold', TONES[tone].text)}>{TONES[tone].label}</span>
                  {finding.owner !== 'none' && <span className="text-muted-foreground"> · Owner: {OWNERS[finding.owner] ?? finding.owner}</span>}
                </p>
              )}
            </div>
            <span className="text-right text-[11px] whitespace-nowrap text-muted-foreground">
              {!flagged && <span className="mr-2">{TONES[tone].label}</span>}
              <span className="code">{finding.code}</span>
            </span>
          </li>
        )
      })}
    </ul>
  )
}
