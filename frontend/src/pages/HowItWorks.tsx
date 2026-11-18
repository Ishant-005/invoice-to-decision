// Screen 5: how the process works. The process map, the rules and thresholds in force
// (read from the API) and the assumptions (the project's own ASSUMPTIONS.md).

import { ArrowRight, Sparkles } from 'lucide-react'
import type { ReactNode } from 'react'

import { DecisionBadge, ErrorBox, Eyebrow, Loading, PageHeader, Panel, Tag } from '@/components/common'
import type { Rules } from '@/lib/api'
import { inr } from '@/lib/format'
import { useApi } from '@/lib/useApi'

// The assumptions document itself, bundled when the app is built, so this page and the
// document cannot drift apart.
import assumptionsText from '../../../docs/ASSUMPTIONS.md?raw'

export function HowItWorks() {
  const rules = useApi<Rules>('/api/config/rules')

  return (
    <>
      <PageHeader
        title="How it works"
        description="One invoice goes through six stages, always in this order. Every stage records what it did, and that record is what the run view shows."
      />

      <div className="rounded-lg border border-primary/25 bg-accent px-5 py-4">
        <p className="text-lg font-semibold tracking-tight">The AI model reads. Code decides.</p>
        <p className="mt-1 max-w-4xl leading-relaxed text-foreground/85">
          The AI model is used in exactly one place: turning the PDF into a structured record. Every check and the
          decision itself are ordinary code, so the same invoice against the same books always gets the same
          decision, and every sentence of the explanation is assembled from real check results.
        </p>
      </div>

      <h2 className="mt-8 mb-3 text-base font-semibold">The process map</h2>
      <ProcessMap rules={rules.data} />

      <div className="mt-4 grid grid-cols-3 gap-3">
        <Outcome decision="APPROVE" when="No finding needs a person.">
          The purchase order's billed amount goes up by the invoice's amount before tax, in the same step as the
          decision.
        </Outcome>
        <Outcome decision="REVIEW" when="At least one finding needs a person, and none blocks payment.">
          The finding names an owner: Accounts Payable, Procurement or the vendor. A reviewer then approves or
          rejects with a comment. Nothing is booked until then.
        </Outcome>
        <Outcome decision="REJECT" when="At least one finding blocks payment.">
          For example an exact duplicate or a vendor that has not been onboarded. Nothing is booked, and a corrected
          invoice can be submitted again.
        </Outcome>
      </div>
      <p className="mt-3 max-w-4xl text-muted-foreground">
        The decision is the most serious outcome among all the findings. Checks do not stop at the first problem:
        every check that can run does run, so a reviewer gets one complete list. A check that cannot run because of an
        earlier problem is recorded as not checked, with the reason.
      </p>

      <h2 className="mt-9 mb-1 text-base font-semibold">Rules and thresholds in force</h2>
      <p className="mb-3 text-muted-foreground">
        Read just now from the server, which reads them from <code className="code">config/rules.yaml</code>.
        Changing a number there changes the decisions; no code is edited.
      </p>
      {rules.loading ? (
        <Panel>
          <Loading label="Loading the rules…" />
        </Panel>
      ) : rules.error || !rules.data ? (
        <ErrorBox message={rules.error ?? 'The rules could not be loaded.'} onRetry={rules.reload} />
      ) : (
        <RulesTable rules={rules.data} />
      )}

      <h2 className="mt-9 mb-1 text-base font-semibold">Assumptions and known limits</h2>
      <p className="mb-3 text-muted-foreground">
        Choices made where the brief was silent, one line each, and what this process does not do. This is the
        project's assumptions document, shown as written.
      </p>
      <Assumptions />
    </>
  )
}

// --- Process map -----------------------------------------------------------------------

function ProcessMap({ rules }: { rules: Rules | null }) {
  // Thresholds are filled in from the API once it has answered.
  const r = rules?.rules
  const v = rules?.validate
  const m = rules?.match
  const stages: { name: string; question: string; ai?: boolean; points: string[]; stops: string }[] = [
    {
      name: 'Receive',
      question: 'Is this a file we can process?',
      points: ['PDF only, up to 10 MB and 5 pages', 'Fingerprints the file (SHA-256)', 'Renders each page as an image', 'Notes a file it has seen before'],
      stops: 'A bad file stops the run here.',
    },
    {
      name: 'Extract',
      question: 'What does the document say?',
      ai: true,
      points: ['One call to the AI model per invoice', 'Returns a structured record with the words it read each key field from', 'A field that is not printed comes back empty, never guessed', 'Each reading is saved by file fingerprint'],
      stops: 'If the model cannot be reached and nothing is saved, the run stops here.',
    },
    {
      name: 'Validate',
      question: 'Is the invoice consistent with itself?',
      points: [
        'It is an invoice, with number, vendor, date and total',
        `Lines multiply out and totals add up${v ? `, within ${inr(v.rounding_tolerance_rupees)}` : ''}`,
        `Date is valid${v ? `; older than ${v.max_invoice_age_days} days is noted` : ''}`,
        `Amounts are positive${v ? `, in ${v.currency}` : ''}; GSTIN is well formed`,
        'Works out the amount before tax',
      ],
      stops: 'Never stops the run.',
    },
    {
      name: 'Match',
      question: 'Which vendor and purchase order?',
      points: [
        'Vendor by GSTIN, else by cleaned name',
        `A merely similar name${m ? ` (score ${m.vendor_fuzzy_min_score}+)` : ''} is only suggested`,
        'A quoted PO must exist and belong to the vendor',
        `No PO quoted: open POs are scored${m ? `; ${m.implied_po_strong_score}+ is suggested` : ''}, never auto-approved`,
        'Invoice lines are paired with PO lines',
      ],
      stops: 'Never stops the run.',
    },
    {
      name: 'Rules',
      question: 'Does it comply with policy?',
      points: [
        'Exact duplicate: same file, or same vendor and number',
        'Probable duplicate: same vendor and total, with the same date or a near-identical number',
        `PO balance${r ? `: may go over by at most ${r.po_overage_max_percent}% and ${inr(r.po_overage_max_rupees)}` : ''}`,
        `Unit prices${r ? ` within ${r.price_variance_max_percent}%` : ''} of the PO`,
        'The PO is open',
      ],
      stops: 'Never stops the run.',
    },
    {
      name: 'Decide',
      question: 'What should happen, and who acts?',
      points: ['Takes the most serious finding', 'Writes the headline, reasons, owner and next step from templates', 'On approval, updates the PO balance in the same step'],
      stops: 'Always ends in a decision.',
    },
  ]

  return (
    <div className="grid grid-cols-6 gap-2">
      {stages.map((stage, index) => (
        <Panel key={stage.name} className={stage.ai ? 'relative flex flex-col border-primary/40' : 'relative flex flex-col'}>
          {index < stages.length - 1 && (
            <span className="absolute top-4 -right-[13px] z-10 flex size-[18px] items-center justify-center rounded-full border bg-card text-muted-foreground">
              <ArrowRight className="size-3" />
            </span>
          )}
          <div className="border-b px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span className="num flex size-5 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">
                {index + 1}
              </span>
              <span className="font-semibold">{stage.name}</span>
              {stage.ai ? (
                <Tag className="ml-auto border-primary/25 bg-accent text-accent-foreground">
                  <Sparkles className="size-3" /> AI
                </Tag>
              ) : (
                <Tag className="ml-auto">Code</Tag>
              )}
            </div>
            <p className="mt-1.5 text-[13px] leading-snug font-medium">{stage.question}</p>
          </div>
          <ul className="space-y-1.5 px-3 py-2.5 text-[12.5px] leading-snug text-foreground/80">
            {stage.points.map((point) => (
              <li key={point} className="flex gap-1.5">
                <span className="mt-[7px] size-1 shrink-0 rounded-full bg-muted-foreground/60" />
                {point}
              </li>
            ))}
          </ul>
          <p className="mt-auto border-t px-3 py-2 text-[11.5px] text-muted-foreground">{stage.stops}</p>
        </Panel>
      ))}
    </div>
  )
}

function Outcome({ decision, when, children }: { decision: 'APPROVE' | 'REVIEW' | 'REJECT'; when: string; children: ReactNode }) {
  return (
    <Panel className="px-4 py-3">
      <DecisionBadge decision={decision} />
      <p className="mt-2 font-medium">{when}</p>
      <p className="mt-1 text-[13px] leading-relaxed text-muted-foreground">{children}</p>
    </Panel>
  )
}

// --- Rules -----------------------------------------------------------------------------

function RulesTable({ rules }: { rules: Rules }) {
  const { validate: v, match: m, rules: r } = rules
  // Stage, what the rule means in plain English, the value in force, and its name in the file.
  const groups: { stage: string; rows: [string, string, string][] }[] = [
    {
      stage: 'Validate',
      rows: [
        ['Arithmetic on the invoice may be off by up to this much, to allow for rounding', inr(v.rounding_tolerance_rupees), 'rounding_tolerance_rupees'],
        ['An invoice older than this gets a note', `${v.max_invoice_age_days} days`, 'max_invoice_age_days'],
        ['The only currency accepted', v.currency, 'currency'],
      ],
    },
    {
      stage: 'Match',
      rows: [
        ['Words ignored when comparing vendor names', m.vendor_name_suffixes.join(', '), 'vendor_name_suffixes'],
        ['A vendor name at least this similar is suggested for a person to confirm, never accepted on its own', `${m.vendor_fuzzy_min_score} / 100`, 'vendor_fuzzy_min_score'],
        ['An invoice line and a PO line at least this similar count as the same item', `${m.line_match_min_score} / 100`, 'line_match_min_score'],
        [
          'Finding a PO when none is quoted: points for the amount fitting the balance, the descriptions matching, and the date being on or after the PO',
          `${m.implied_po_points_amount_fits} + ${m.implied_po_points_description} + ${m.implied_po_points_date}`,
          'implied_po_points_*',
        ],
        ['A PO scoring at least this is a strong candidate and is suggested', `${m.implied_po_strong_score} / 100`, 'implied_po_strong_score'],
      ],
    },
    {
      stage: 'Rules',
      rows: [
        ['An invoice may take a PO over its value by at most this share of the PO value…', `${r.po_overage_max_percent}%`, 'po_overage_max_percent'],
        ['…and by at most this amount. Both limits must hold; beyond them a person decides', inr(r.po_overage_max_rupees), 'po_overage_max_rupees'],
        ['A unit price may differ from the PO price by up to this much, either way', `${r.price_variance_max_percent}%`, 'price_variance_max_percent'],
        ['Two invoice numbers are "nearly the same" if one is the other plus at most this many characters', String(r.duplicate_max_extra_characters), 'duplicate_max_extra_characters'],
      ],
    },
  ]

  return (
    <Panel>
      <table className="w-full text-left">
        <thead>
          <tr className="border-b text-xs text-muted-foreground [&>th]:px-4 [&>th]:py-2 [&>th]:font-medium">
            <th className="w-[100px]">Stage</th>
            <th>Rule</th>
            <th className="w-[150px] text-right">In force</th>
            <th className="w-[270px]">Name in rules.yaml</th>
          </tr>
        </thead>
        <tbody>
          {groups.map((group) =>
            group.rows.map(([meaning, value, key], index) => (
              <tr key={key} className="border-b last:border-b-0 [&>td]:px-4 [&>td]:py-2">
                <td className="font-semibold">{index === 0 && group.stage}</td>
                <td className="text-foreground/85">{meaning}</td>
                <td className="num text-right font-semibold">{value}</td>
                <td className="code text-muted-foreground">{key}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </Panel>
  )
}

// --- Assumptions -----------------------------------------------------------------------

/** Split the Markdown into its "## " sections, each a list of "- " lines. */
function parseSections(markdown: string): { title: string; items: string[] }[] {
  const sections: { title: string; items: string[] }[] = []
  for (const line of markdown.split('\n')) {
    if (line.startsWith('## ')) sections.push({ title: line.slice(3).trim(), items: [] })
    else if (line.startsWith('- ') && sections.length > 0) sections[sections.length - 1].items.push(line.slice(2).trim())
  }
  return sections
}

/** Show `code` spans from the Markdown in a code font; everything else as plain text. */
function InlineCode({ text }: { text: string }) {
  return (
    <>
      {text.split('`').map((part, index) =>
        index % 2 === 1 ? (
          <code key={index} className="code rounded bg-muted px-1 py-px">
            {part}
          </code>
        ) : (
          part
        ),
      )}
    </>
  )
}

const SECTION_NOTES: Record<string, string> = {
  'Milestone 0': 'Project set-up',
  'Milestone 1': 'Data and test invoices',
  'Milestone 2': 'Decision logic',
  'Milestone 3': 'Reading the invoice with the AI model',
  'Milestone 4': 'Pipeline and API',
  'Milestone 5': 'Web app',
}

function Assumptions() {
  const sections = parseSections(assumptionsText)
  if (sections.length === 0) return <Panel className="p-4 text-muted-foreground">The assumptions document is empty.</Panel>
  return (
    <div className="space-y-2">
      {sections.map((section, index) => (
        <Panel key={section.title}>
          {/* The first section (known limits) starts open; the rest open on a click. */}
          <details open={index === 0} className="group">
            <summary className="flex cursor-pointer list-none items-center gap-3 px-4 py-2.5">
              <ArrowRight className="size-3.5 text-muted-foreground transition-transform group-open:rotate-90" />
              <span className="font-semibold">{section.title}</span>
              {SECTION_NOTES[section.title] && <span className="text-muted-foreground">{SECTION_NOTES[section.title]}</span>}
              <Eyebrow className="ml-auto">{section.items.length} items</Eyebrow>
            </summary>
            <ul className="space-y-2 border-t px-4 py-3 pl-11 text-[13px] leading-relaxed text-foreground/85">
              {section.items.map((item) => (
                <li key={item} className="list-disc">
                  <InlineCode text={item} />
                </li>
              ))}
            </ul>
          </details>
        </Panel>
      ))}
    </div>
  )
}
