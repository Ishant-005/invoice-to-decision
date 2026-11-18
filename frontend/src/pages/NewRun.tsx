// Screen 2: start a run, either by uploading a PDF or by picking one of the 13 samples.

import { FileUp, Loader2, ScanLine } from 'lucide-react'
import { useRef, useState } from 'react'
import { useNavigate } from 'react-router'

import { ErrorBox, Loading, PageHeader, Panel, Tag } from '@/components/common'
import { type Sample, startSampleRun, startUploadRun } from '@/lib/api'
import { useApi } from '@/lib/useApi'
import { cn } from '@/lib/utils'

const MAX_BYTES = 10 * 1024 * 1024 // the server enforces this too; checking here saves a wasted upload

export function NewRun() {
  const navigate = useNavigate()
  const samples = useApi<Sample[]>('/api/samples')
  const [starting, setStarting] = useState<string | null>(null) // the file being submitted
  const [error, setError] = useState<string | null>(null)

  // Submit, then go straight to the run view, which follows the run live.
  async function start(name: string, submit: () => Promise<{ id: string }>) {
    setStarting(name)
    setError(null)
    try {
      const run = await submit()
      navigate(`/runs/${run.id}`)
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The run could not be started.')
      setStarting(null)
    }
  }

  function upload(file: File | undefined) {
    if (!file) return
    if (file.size > MAX_BYTES) {
      setError(`${file.name} is ${(file.size / (1024 * 1024)).toFixed(1)} MB. The limit is 10 MB.`)
      return
    }
    start(file.name, () => startUploadRun(file))
  }

  return (
    <>
      <PageHeader
        title="New run"
        description="Submit one invoice. It goes through all six stages and you watch each one as it happens."
      />

      <Dropzone onFile={upload} busy={starting !== null} />

      {error && (
        <div className="mt-4">
          <ErrorBox message={error} />
        </div>
      )}

      <div className="mt-8 mb-3 flex items-baseline justify-between">
        <h2 className="font-semibold">Or run a sample invoice</h2>
        <p className="text-xs text-muted-foreground">
          13 invoices from five vendors. The descriptions say what each document is, not what
          the process will decide.
        </p>
      </div>

      {samples.loading ? (
        <Loading label="Loading the sample invoices…" />
      ) : samples.error ? (
        <ErrorBox message={samples.error} onRetry={samples.reload} />
      ) : (
        <div className="grid grid-cols-4 gap-3 xl:grid-cols-5">
          {samples.data?.map((sample) => (
            <SampleCard
              key={sample.file}
              sample={sample}
              busy={starting === sample.file}
              disabled={starting !== null}
              onRun={() => start(sample.file, () => startSampleRun(sample.file))}
            />
          ))}
        </div>
      )}
    </>
  )
}

function Dropzone({ onFile, busy }: { onFile: (file: File | undefined) => void; busy: boolean }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)

  return (
    <button
      type="button"
      disabled={busy}
      onClick={() => input.current?.click()}
      onDragOver={(event) => {
        event.preventDefault()
        setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(event) => {
        event.preventDefault()
        setOver(false)
        onFile(event.dataTransfer.files[0])
      }}
      className={cn(
        'flex w-full items-center justify-center gap-4 rounded-lg border border-dashed bg-card px-6 py-9 text-left transition-colors',
        over ? 'border-primary bg-accent' : 'border-input hover:border-primary/60 hover:bg-accent/40',
        busy && 'pointer-events-none opacity-60',
      )}
    >
      <span className="flex size-11 items-center justify-center rounded-full bg-accent text-accent-foreground">
        {busy ? <Loader2 className="size-5 animate-spin" /> : <FileUp className="size-5" />}
      </span>
      <span>
        <span className="block text-base font-medium">
          {busy ? 'Starting the run…' : 'Drop an invoice PDF here, or click to choose one'}
        </span>
        <span className="mt-0.5 block text-muted-foreground">
          PDF only, up to 10 MB and 5 pages. Digital or scanned.
        </span>
      </span>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        onChange={(event) => {
          onFile(event.target.files?.[0])
          event.target.value = '' // so choosing the same file again still counts as a change
        }}
      />
    </button>
  )
}

function SampleCard({
  sample,
  busy,
  disabled,
  onRun,
}: {
  sample: Sample
  busy: boolean
  disabled: boolean
  onRun: () => void
}) {
  // "Acme Packaging: corrugated boxes…" -> vendor in bold, the rest underneath.
  const [vendor, ...rest] = sample.description.split(': ')
  const contents = rest.join(': ')

  return (
    <Panel className="group overflow-hidden transition-shadow hover:shadow-sm">
      <button type="button" onClick={onRun} disabled={disabled} className="block w-full text-left disabled:opacity-60">
        <div className="relative h-36 overflow-hidden border-b bg-muted">
          {/* The real first page of the PDF, rendered by the server. */}
          <img
            src={`/api/samples/${sample.file}/preview.png`}
            alt={`First page of ${sample.file}`}
            loading="lazy"
            className="w-full object-cover object-top"
          />
          {busy && (
            <span className="absolute inset-0 flex items-center justify-center gap-2 bg-card/80 font-medium">
              <Loader2 className="size-4 animate-spin" /> Starting…
            </span>
          )}
        </div>
        <div className="p-3">
          <p className="font-medium">
            <span className="num mr-1.5 text-muted-foreground">{String(sample.case).padStart(2, '0')}</span>
            {vendor}
          </p>
          <p className="mt-0.5 min-h-10 text-[13px] leading-snug text-muted-foreground first-letter:uppercase">
            {contents}
          </p>
          <div className="mt-2.5 flex items-center justify-between">
            {sample.scanned ? (
              <Tag>
                <ScanLine className="size-3" /> Scanned image
              </Tag>
            ) : (
              <Tag>Digital PDF</Tag>
            )}
            <span className="text-xs font-medium text-primary opacity-0 transition-opacity group-hover:opacity-100">
              Run this invoice →
            </span>
          </div>
        </div>
      </button>
    </Panel>
  )
}
