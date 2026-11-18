// The six stages: their names and what each one does, in a sentence.

import type { StageName } from '@/lib/api'

export const STAGE_INFO: Record<StageName, { name: string; does: string }> = {
  receive: { name: 'Receive', does: 'Checks the file, fingerprints it and renders the page' },
  extract: { name: 'Extract', does: 'The AI model reads the document into a structured record' },
  validate: { name: 'Validate', does: 'Is the invoice complete and consistent with itself?' },
  match: { name: 'Match', does: 'Which vendor and purchase order does it belong to?' },
  rules: { name: 'Rules', does: 'Does it comply with company policy?' },
  decide: { name: 'Decide', does: 'Combines every finding into one decision' },
}
