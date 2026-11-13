'use client'

import { useState, useEffect, use, Suspense } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { useRouter } from 'next/navigation'
import { ArrowRight, Lock, FileX, MessageSquare } from 'lucide-react'
import { format } from 'date-fns'
import { DashboardLayout } from '@/components/dashboard-layout'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { cn } from '@/lib/utils'

type TranscriptLine = { speaker: string; text: string }

type SessionMeta = {
  status?: string
  created_at?: string | null
  end_time?: string | null
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

function TranscriptContent({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params)
  const [lines, setLines] = useState<TranscriptLine[] | null>(null)
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
          .select('speaker, text')
          .eq('session_id', sessionId)
          .order('created_at')
        setLines(data ?? [])
      } catch (error) {
        console.error('Error fetching transcript:', error)
        setLines([])
      }
    }
    load()
  }, [sessionId, router])

  return (
    <DashboardLayout title="Session Transcript">
      <div className="mx-auto max-w-3xl space-y-6 p-4 md:p-8">
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
            ) : (
              <div className="space-y-4 rounded-xl border bg-card p-6">
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
                          {isUser ? (
                            <p className="whitespace-pre-wrap break-words">{line.text}</p>
                          ) : (
                            <p className="whitespace-pre-wrap break-words leading-relaxed">{line.text}</p>
                          )}
                        </BubbleContent>
                      </Bubble>
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>
    </DashboardLayout>
  )
}
