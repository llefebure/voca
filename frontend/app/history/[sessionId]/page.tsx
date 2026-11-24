'use client'

import { useState, useEffect, use, Suspense } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useRouter } from 'next/navigation'
import { ArrowRight, Lock, FileX, MessageSquare, PanelRightIcon } from 'lucide-react'
import { format } from 'date-fns'
import { DashboardLayout } from '@/components/dashboard-layout'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Markdown } from '@/components/markdown'
import { displayPanel } from '@/components/panel/panel-components'
import type { PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'
import { cn } from '@/lib/utils'

type TranscriptLine = { speaker: string; text: string }

type SessionMeta = {
  status?: string
  created_at?: string | null
  end_time?: string | null
}

/**
 * A canvas artifact generated during the session. All artifacts appear in the
 * tabbed panel — hidden ones too (they were still shown to the learner).
 * A later `panel_shown` row with the same id replaces earlier content.
 */
type PanelArtifact = PanelInstance

/** Walks transcript rows into chat lines + panel artifacts by payload kind. */
function walkTranscripts(
  rows: { speaker: string; text: string; payload?: { kind?: string; data?: unknown } | null }[],
): { lines: TranscriptLine[]; panels: PanelArtifact[] } {
  const lines: TranscriptLine[] = []
  const panels = new Map<string, PanelArtifact>()
  for (const row of rows) {
    const payload = row.payload
    if (row.speaker === 'system' && payload?.kind) {
      if (payload.kind === 'panel_shown') {
        const panel = cleanEscapedText((payload.data as { panel?: PanelInstance }).panel)
        // Markdown-only panels; ignore legacy content shapes.
        if (panel?.id && typeof panel.markdown === 'string') panels.set(panel.id, panel)
      }
      // panel_hidden rows are walk bookkeeping; the artifact itself stays a tab.
      continue
    }
    if (!String(row.text ?? '').trim()) continue
    lines.push({ speaker: row.speaker, text: row.text })
  }
  return { lines, panels: [...panels.values()] }
}

export default function TranscriptPage({ params }: { params: Promise<{ sessionId: string }> }) {
  // Params are unwrapped inside <Suspense> so the route prerenders a static shell
  // (Next 16 cache-components validation — same pattern as the recap page).
  return (
    <Suspense fallback={<TranscriptLoading />}>
      <TranscriptContent params={params} />
    </Suspense>
  )
}

function TranscriptLoading() {
  return (
    <DashboardLayout title="Session Transcript">
      <div className="flex h-full items-center justify-center text-muted-foreground">
        Loading transcript...
      </div>
    </DashboardLayout>
  )
}

/** The canvas side of the split: tab bar (per artifact) + the active artifact. */
function ArtifactTabs({
  panels,
  activeIndex,
  onSelect,
}: {
  panels: PanelArtifact[]
  activeIndex: number
  onSelect: (index: number) => void
}) {
  const active = panels[Math.min(activeIndex, panels.length - 1)]
  return (
    <div className="flex max-h-full min-h-0 flex-col gap-2" data-testid="transcript-artifacts">
      {panels.length > 1 ? (
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Panel artifacts">
          {panels.map((panel, index) => (
            <button
              key={panel.id}
              type="button"
              role="tab"
              aria-selected={index === activeIndex}
              data-testid={`artifact-tab-${index}`}
              className={cn(
                'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                index === activeIndex
                  ? 'bg-primary text-primary-foreground'
                  : 'bg-muted text-muted-foreground hover:text-foreground',
              )}
              onClick={() => onSelect(index)}
            >
              <PanelRightIcon className="size-3" />
              <span className="max-w-[180px] truncate">{panel.title}</span>
            </button>
          ))}
        </div>
      ) : (
        <div className="flex items-center gap-1.5 px-1 text-xs font-medium tracking-wide text-muted-foreground uppercase">
          <PanelRightIcon className="size-3" />
          {active.title}
        </div>
      )}
      {active ? (
        <div className="flex max-h-[65vh] min-h-0 flex-1 flex-col rounded-xl border border-primary/30 bg-card shadow-sm">
          <div className="flex-1 overflow-y-auto px-4 py-3">
            <Markdown breaks className="prose-invert-none">{displayPanel(active).markdown}</Markdown>
          </div>
        </div>
      ) : null}
    </div>
  )
}

function TranscriptContent({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params)
  const [lines, setLines] = useState<TranscriptLine[] | null>(null)
  const [panels, setPanels] = useState<PanelArtifact[]>([])
  const [activePanelIndex, setActivePanelIndex] = useState(0)
  const [meta, setMeta] = useState<SessionMeta | null>(null)
  const [notFound, setNotFound] = useState(false)
  const router = useRouter()

  useEffect(() => {
    const load = async () => {
      try {
        const { data: { session: auth } } = await supabase.auth.getSession()
        if (!auth) {
          router.push('/auth')
          return
        }
        const { data: sessionRow } = await supabase
          .from('sessions')
          .select('status, created_at, end_time')
          .eq('id', sessionId)
          .maybeSingle()
        if (!sessionRow) {
          setNotFound(true)
          return
        }
        setMeta(sessionRow as SessionMeta)
        const { data } = await supabase
          .from('transcripts')
          .select('speaker, text, payload')
          .eq('session_id', sessionId)
          .order('created_at')
        const walked = walkTranscripts((data ?? []) as never)
        setLines(walked.lines)
        setPanels(walked.panels)
        setActivePanelIndex(0)
      } catch (error) {
        console.error('Error fetching transcript:', error)
        setLines([])
      }
    }
    load()
  }, [sessionId, router])

  const hasPanels = panels.length > 0

  return (
    <DashboardLayout title="Session Transcript">
      <div
        className={cn(
          'mx-auto space-y-6 p-4 md:p-8',
          hasPanels ? 'w-full max-w-6xl' : 'max-w-3xl',
        )}
      >
        {notFound ? (
          <div className="text-center py-20 space-y-4">
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
              <FileX className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium">Session not found</h3>
            <Button variant="outline" onClick={() => router.push('/history')}>
              Back to History
            </Button>
          </div>
        ) : (
          <>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                {meta?.created_at && (
                  <span className="text-sm text-muted-foreground">
                    {format(new Date(meta.created_at), 'PPP p')}
                  </span>
                )}
                {meta?.status && (
                  <Badge variant="secondary" className="capitalize">
                    {meta.status}
                  </Badge>
                )}
              </div>
              <div className="flex items-center gap-2">
                {meta?.status === 'active' ? (
                  <>
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      Session still in progress
                    </span>
                    <Button
                      variant="default"
                      size="sm"
                      onClick={() => router.push(`/?session=${sessionId}`)}
                    >
                      <MessageSquare className="h-3 w-3" /> Continue
                    </Button>
                  </>
                ) : (
                  <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Lock className="h-3 w-3" /> Read-only · this session has ended
                  </span>
                )}
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => router.push(`/recap/${sessionId}`)}
                >
                  View Recap <ArrowRight className="h-3 w-3" />
                </Button>
              </div>
            </div>

            {lines === null ? (
              <div className="flex h-64 items-center justify-center text-muted-foreground">
                Loading transcript...
              </div>
            ) : lines.length === 0 ? (
              <div className="text-center py-20 space-y-4">
                <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
                  <FileX className="h-8 w-8 text-muted-foreground" />
                </div>
                <h3 className="text-lg font-medium">No conversation recorded</h3>
                <p className="text-muted-foreground">
                  Nothing was said in this session, so there is no transcript.
                </p>
              </div>
            ) : hasPanels ? (
              // Split view: the conversation on the left, the canvas artifacts
              // on the right (tabs when more than one was generated).
              <div className="grid grid-cols-1 items-start gap-6 md:grid-cols-[minmax(0,1fr)_400px]">
                <div className="min-w-0 space-y-4 rounded-xl border bg-card p-6">
                  <TranscriptLineList lines={lines} />
                </div>
                <ArtifactTabs
                  panels={panels}
                  activeIndex={activePanelIndex}
                  onSelect={setActivePanelIndex}
                />
              </div>
            ) : (
              <div className="space-y-4 rounded-xl border bg-card p-6">
                <TranscriptLineList lines={lines} />
              </div>
            )}
          </>
        )}
      </div>
    </DashboardLayout>
  )
}

function TranscriptLineList({ lines }: { lines: TranscriptLine[] }) {
  return (
    <>
      {lines.map((line, index) => {
        const isUser = line.speaker === 'user'
        return (
          <div
            key={`${line.speaker}-${index}`}
            className={cn('flex', isUser ? 'justify-end' : 'justify-start')}
          >
            <Bubble
              variant={isUser ? 'default' : 'muted'}
              align={isUser ? 'end' : 'start'}
              className="max-w-[85%]"
            >
              <BubbleContent>
                <p className="whitespace-pre-wrap break-words leading-relaxed">{line.text}</p>
              </BubbleContent>
            </Bubble>
          </div>
        )
      })}
    </>
  )
}
