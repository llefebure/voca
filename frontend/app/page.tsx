'use client'

import * as React from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport, type UIMessage } from 'ai'
import { Suspense } from 'react'
import {
  ArrowUpIcon,
  FlagIcon,
  LanguagesIcon,
  MessageSquarePlusIcon,
  SquareIcon,
  Volume2Icon,
  VolumeXIcon,
} from 'lucide-react'

import { supabase } from '@/lib/supabase'
import { BACKEND_URL } from '@/lib/api'
import {
  DEFAULT_LANGUAGE,
  languageName,
  lessonTemplateName,
} from '@/lib/languages'
import { useLanguage } from '@/components/language-context'
import { useSpeech } from '@/lib/use-speech'
import { DashboardLayout } from '@/components/dashboard-layout'
import { Markdown } from '@/components/markdown'
import { Avatar, AvatarFallback } from '@/components/ui/avatar'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from '@/components/ui/empty'
import {
  InputGroup,
  InputGroupAddon,
  InputGroupButton,
  InputGroupTextarea,
} from '@/components/ui/input-group'
import {
  Message,
  MessageAvatar,
  MessageContent,
  MessageHeader,
} from '@/components/ui/message'
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller'
import { Bubble, BubbleContent } from '@/components/ui/bubble'
import { Spinner } from '@/components/ui/spinner'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { toast } from '@/components/ui/toast'

const TUTOR_AVATAR = (
  <Avatar className="size-8">
    <AvatarFallback>V</AvatarFallback>
  </Avatar>
)

/** The enriched session plan as stored by POST /sessions/plan. */
type VocaSessionPlan = {
  lesson?: {
    template?: string
    topic?: string
    scenario?: string | null
    objectives?: string[]
  }
  opening_hook?: string
  cards?: { id: string; front: string; back: string }[]
}

export default function ChatPage() {
  // The `?session=` continue param is unwrapped inside <Suspense> so the route
  // prerenders a static shell (Next 16 cache-components validation).
  return (
    <Suspense fallback={<ChatPageLoading />}>
      <ChatPageContent />
    </Suspense>
  )
}

function ChatPageLoading() {
  return (
    <DashboardLayout title="Conversation Tutor">
      <div className="flex h-full items-center justify-center text-muted-foreground">Loading session…</div>
    </DashboardLayout>
  )
}

function ChatPageContent() {
  const router = useRouter()
  const { activeLanguage, loading: languageLoading } = useLanguage()
  const searchParams = useSearchParams()
  const continueSessionId = searchParams.get('session')

  // Auth check (profile existence gates onboarding; the language lives in context).
  React.useEffect(() => {
    const checkUser = async () => {
      const {
        data: { user },
      } = await supabase.auth.getUser()
      if (!user) {
        router.push('/auth')
        return
      }
      const { data: profile } = await supabase
        .from('profiles')
        .select('id')
        .eq('id', user.id)
        .maybeSingle()
      if (!profile) {
        router.push('/onboarding')
        return
      }
    }
    checkUser()
  }, [router])

  // The shared active-language pointer; falls back while the context loads.
  const targetLanguage = activeLanguage ?? DEFAULT_LANGUAGE

  return (
    <DashboardLayout title="Conversation Tutor">
      {/* Keying on the language resets all chat state when the user toggles languages:
          the previous conversation stays open in History under its own language (the
          same semantics as "New session") — nothing is auto-resumed after a toggle.
          The continue param only reaches the view once the context has resolved. */}
      <ChatView
        key={targetLanguage}
        targetLanguage={targetLanguage}
        continueSessionId={languageLoading ? null : continueSessionId}
      />
    </DashboardLayout>
  )
}

function ChatView({
  targetLanguage,
  continueSessionId,
}: {
  targetLanguage: string
  continueSessionId: string | null
}) {
  const router = useRouter()
  const { muted, toggleMuted, speakingId, speak, stop } = useSpeech()
  const [input, setInput] = React.useState('')
  const [submitting, setSubmitting] = React.useState(false)
  const [ending, setEnding] = React.useState(false)
  const [confirmEnd, setConfirmEnd] = React.useState(false)
  const [sessionId, setSessionId] = React.useState<string | null>(null)
  const [plan, setPlan] = React.useState<VocaSessionPlan | null>(null)
  const [planning, setPlanning] = React.useState(false)
  const sessionIdRef = React.useRef<string | null>(null)
  const lastSpokenRef = React.useRef<string | null>(null)
  // Synchronous guard for Enter-key double submits: state alone can lag one render.
  const submittingRef = React.useRef(false)

  const transport = React.useMemo(
    () =>
      new DefaultChatTransport({
        api: '/api/chat',
        // Inject a fresh auth header on every request and merge the per-call
        // `sessionId` (passed by `sendMessage`) into the body. Runs at request
        // time only, never during render.
        prepareSendMessagesRequest: async ({ messages, body }) => {
          const {
            data: { session },
          } = await supabase.auth.getSession()
          if (!session?.access_token) {
            throw new Error('Your session has expired. Please sign in again.')
          }
          const options = (body ?? {}) as { sessionId?: string }
          return {
            body: { messages, sessionId: options.sessionId },
            headers: { Authorization: `Bearer ${session.access_token}` },
          }
        },
      }),
    [],
  )

  const { messages, sendMessage, status, setMessages } = useChat({
    transport,
    onError: (error) => {
      toast({ title: 'Chat error', description: error.message, type: 'error' })
    },
  })

  const streaming = status === 'streaming' || status === 'submitted'

  /** Generate the session's lesson plan; best-effort, surfaced in the header. */
  async function planSession(id: string) {
    setPlanning(true)
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession()
      const response = await fetch(
        `${BACKEND_URL}/sessions/plan?session_id=${encodeURIComponent(id)}`,
        { method: 'POST', headers: { Authorization: `Bearer ${session?.access_token}` } },
      )
      if (!response.ok) throw new Error(String(response.status))
      setPlan((await response.json()) as VocaSessionPlan)
    } catch {
      // Planning is best-effort; the tutor still works without a plan.
      setPlan(null)
      toast({
        title: 'Planning unavailable',
        description: 'Could not plan this session — starting without a lesson plan.',
        type: 'error',
      })
    } finally {
      setPlanning(false)
    }
  }

  /** Reuse or lazily create the session the conversation belongs to. Event-time only. */
  async function activeSessionId(): Promise<string> {
    const cached = sessionIdRef.current
    if (cached) return cached
    const {
      data: { session },
    } = await supabase.auth.getSession()
    if (!session?.access_token) {
      throw new Error('Your session has expired. Please sign in again.')
    }
    const response = await fetch(`${BACKEND_URL}/sessions/start`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${session.access_token}` },
    })
    if (!response.ok) throw new Error('Failed to start a session')
    const data = (await response.json()) as { session_id: string }
    sessionIdRef.current = data.session_id
    setSessionId(data.session_id)
    // Plan the lesson right after the session starts so the tutor greets with it.
    await planSession(data.session_id)
    return data.session_id
  }

  // Continue an open session (History's Continue button links /?session=<id>): the
  // ONLY restore path — nothing auto-resumes on load or toggle. Verifies ownership
  // and open status under RLS, restores the stored plan, and replays the transcript
  // so the conversation (and its proxy-sent history) continues seamlessly.
  React.useEffect(() => {
    if (!continueSessionId) return
    let cancelled = false
    void (async () => {
      try {
        const { data: sessionRow } = await supabase
          .from('sessions')
          .select('id, status, plan')
          .eq('id', continueSessionId)
          .maybeSingle()
        if (cancelled) return
        if (!sessionRow || sessionRow.status !== 'active') {
          toast({
            title: 'Session unavailable',
            description: 'That conversation has ended or does not exist.',
            type: 'error',
          })
          return
        }
        const { data: transcript } = await supabase
          .from('transcripts')
          .select('speaker, text')
          .eq('session_id', sessionRow.id)
          .order('created_at')
        if (cancelled) return
        sessionIdRef.current = sessionRow.id
        setSessionId(sessionRow.id)
        setPlan((sessionRow.plan as VocaSessionPlan | null) ?? null)
        const restored: UIMessage[] = (transcript ?? []).map((line, index) => ({
          id: `restored-${index}`,
          role: line.speaker === 'user' ? ('user' as const) : ('assistant' as const),
          parts: [{ type: 'text' as const, text: line.text }],
        }))
        setMessages(restored)
        const last = restored[restored.length - 1]
        lastSpokenRef.current = last?.id ?? null // do not re-speak restored history
        // Clean the URL so reloads start fresh instead of re-entering this flow.
        window.history.replaceState(null, '', '/')
      } catch (error) {
        if (!cancelled) {
          toast({
            title: 'Could not continue session',
            description: error instanceof Error ? error.message : 'Something went wrong',
            type: 'error',
          })
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [continueSessionId, setMessages])

  async function handleSubmit(event?: React.FormEvent) {
    event?.preventDefault()
    // The first message awaits /sessions/start (+ lesson planning) before the
    // transport flips `status` out of `ready` and the input clears, so `status`
    // alone lets a second quick Enter double-submit (and could start a duplicate
    // session). Flip the guard synchronously before that window opens.
    if (submittingRef.current) return
    const text = input.trim()
    if (!text || status !== 'ready') return
    submittingRef.current = true
    setSubmitting(true)
    try {
      const activeSession = await activeSessionId()
      setInput('')
      await sendMessage({ text }, { body: { sessionId: activeSession } })
    } catch (error) {
      toast({
        title: 'Chat error',
        description: error instanceof Error ? error.message : 'Failed to start a session',
        type: 'error',
      })
    } finally {
      submittingRef.current = false
      setSubmitting(false)
    }
  }

  // Speak each tutor reply once it has finished streaming.
  React.useEffect(() => {
    if (muted || status !== 'ready') return
    const last = messages[messages.length - 1]
    if (!last || last.role !== 'assistant') return
    if (lastSpokenRef.current === last.id) return
    const text = last.parts
      .filter((part) => part.type === 'text')
      .map((part) => part.text)
      .join('')
    if (!text.trim()) return
    lastSpokenRef.current = last.id
    void speak(last.id, text, targetLanguage)
  }, [messages, muted, speak, status, targetLanguage])

  function handleTranslate(text: string) {
    void (async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/translate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, source_lang: targetLanguage, target_lang: 'en' }),
        })
        if (!response.ok) throw new Error('Translation failed')
        const data = (await response.json()) as { translation: string }
        toast({ title: 'Translation', description: data.translation, type: 'info' })
      } catch (error) {
        toast({
          title: 'Error',
          description: error instanceof Error ? error.message : 'Translation failed',
          type: 'error',
        })
      }
    })()
  }

  // Local clear only: the session row stays active/open in History for its language.
  function startNewSession() {
    stop()
    sessionIdRef.current = null
    lastSpokenRef.current = null
    setPlan(null)
    setMessages([])
  }

  async function endSession() {
    const currentSessionId = sessionIdRef.current
    if (!currentSessionId || ending) return
    setEnding(true)
    try {
      stop()
      const {
        data: { session },
      } = await supabase.auth.getSession()
      const response = await fetch(
        `${BACKEND_URL}/sessions/end?session_id=${encodeURIComponent(currentSessionId)}`,
        { method: 'POST', headers: { Authorization: `Bearer ${session?.access_token}` } },
      )
      // 409 means the session was already ended (e.g. double click) — treat it
      // as success and still clear the page.
      if (!response.ok && response.status !== 409) {
        throw new Error('Failed to end the session')
      }
      // Archive locally: the chat screen must be blank from the moment of
      // ending — before, during, and regardless of how the redirect goes.
      sessionIdRef.current = null
      lastSpokenRef.current = null
      setPlan(null)
      setMessages([])
      setInput('')
      router.push(`/recap/${currentSessionId}`)
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to end the session',
        type: 'error',
      })
    } finally {
      setEnding(false)
    }
  }

  return (
    <div className="relative flex h-full w-full flex-col">
      <div className="flex items-start justify-between gap-4 px-8 pt-6 pb-4">
        <div className="flex flex-col gap-1">
          <div className="font-medium">{languageName(targetLanguage)} Session</div>
          <div className="text-sm text-muted-foreground">
            {planning
              ? 'Planning your session…'
              : plan?.lesson
                ? `Today's lesson: ${lessonTemplateName(plan.lesson.template)} — ${plan.lesson.topic}`
                : 'Practice speaking with your conversation partner.'}
          </div>
        </div>
        <div className="flex items-center gap-1">
          <Tooltip>
            <TooltipTrigger
              render={
                <Button variant="ghost" size="icon" onClick={toggleMuted}>
                  {muted ? <VolumeXIcon /> : <Volume2Icon />}
                </Button>
              }
            />
            <TooltipContent>{muted ? 'Speech is muted' : 'Speech is on'}</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button variant="ghost" size="icon" onClick={startNewSession} disabled={streaming}>
                  <MessageSquarePlusIcon />
                </Button>
              }
            />
            <TooltipContent>New session</TooltipContent>
          </Tooltip>
          <Tooltip>
            <TooltipTrigger
              render={
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={() => setConfirmEnd(true)}
                  disabled={!sessionId || streaming}
                >
                  <FlagIcon />
                </Button>
              }
            />
            <TooltipContent>End session &amp; recap</TooltipContent>
          </Tooltip>
        </div>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-8">
        {messages.length === 0 ? (
          <Empty className="flex-1">
            <EmptyHeader>
              <EmptyMedia variant="icon">
                <LanguagesIcon />
              </EmptyMedia>
              <EmptyTitle>Ready to practice?</EmptyTitle>
              <EmptyDescription>
                Start a conversation in {languageName(targetLanguage)} to improve your fluency.
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <MessageScrollerProvider autoScroll>
              <MessageScroller>
                <MessageScrollerViewport>
                <MessageScrollerContent className="gap-6 py-4">
                  {messages.map((message) => {
                    const isUser = message.role === 'user'
                    const text = message.parts
                      .filter((part) => part.type === 'text')
                      .map((part) => part.text)
                      .join('')
                    return (
                      <MessageScrollerItem
                        key={message.id}
                        messageId={message.id}
                        scrollAnchor={isUser}
                      >
                        <Message align={isUser ? 'end' : 'start'}>
                          {!isUser && (
                            <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>
                          )}
                          <MessageContent>
                            {!isUser && <MessageHeader>Voca</MessageHeader>}
                            <Bubble
                              variant={isUser ? 'default' : 'muted'}
                              align={isUser ? 'end' : 'start'}
                            >
                              <BubbleContent>
                                {isUser ? text : <Markdown>{text}</Markdown>}
                              </BubbleContent>
                            </Bubble>
                            {!isUser && text.trim() && (
                              <div className="flex w-full items-center gap-1 px-1 opacity-40 transition-opacity group-hover/message:opacity-100 focus-within:opacity-100">
                                <Tooltip>
                                  <TooltipTrigger
                                    render={
                                      <Button
                                        variant="ghost"
                                        size="icon-xs"
                                        onClick={() => handleTranslate(text)}
                                      >
                                        <LanguagesIcon />
                                      </Button>
                                    }
                                  />
                                  <TooltipContent>Translate</TooltipContent>
                                </Tooltip>
                                {speakingId === message.id ? (
                                  <Tooltip>
                                    <TooltipTrigger
                                      render={
                                        <Button
                                          variant="ghost"
                                          size="icon-xs"
                                          onClick={stop}
                                        >
                                          <SquareIcon />
                                        </Button>
                                      }
                                    />
                                    <TooltipContent>Stop speaking</TooltipContent>
                                  </Tooltip>
                                ) : (
                                  <Tooltip>
                                    <TooltipTrigger
                                      render={
                                        <Button
                                          variant="ghost"
                                          size="icon-xs"
                                          onClick={() => void speak(message.id, text, targetLanguage)}
                                        >
                                          <Volume2Icon />
                                        </Button>
                                      }
                                    />
                                    <TooltipContent>Replay speech</TooltipContent>
                                  </Tooltip>
                                )}
                              </div>
                            )}
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    )
                  })}
                  {status === 'submitted' && (
                    <MessageScrollerItem messageId="thinking">
                      <Message align="start">
                        <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>
                        <MessageContent>
                          <MessageHeader>Voca</MessageHeader>
                          <Bubble variant="muted" align="start">
                            <BubbleContent>
                              <span className="shimmer">Thinking…</span>
                            </BubbleContent>
                          </Bubble>
                        </MessageContent>
                      </Message>
                    </MessageScrollerItem>
                  )}
                </MessageScrollerContent>
                </MessageScrollerViewport>
                <MessageScrollerButton />
              </MessageScroller>
            </MessageScrollerProvider>
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="px-8 pt-4 pb-8">
        <InputGroup className="h-auto min-h-14 flex-col py-1">
          <InputGroupTextarea
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' && !event.shiftKey) {
                event.preventDefault()
                handleSubmit()
              }
            }}
            placeholder={`Type your message in ${languageName(targetLanguage)}…`}
            aria-label="Message"
            className="min-h-7"
            rows={1}
          />
          <InputGroupAddon align="block-end" className="justify-between">
            <Tooltip>
              <TooltipTrigger
                render={
                  <InputGroupButton
                    variant="ghost"
                    onClick={() => handleTranslate(input)}
                    disabled={!input.trim()}
                  >
                    <LanguagesIcon />
                  </InputGroupButton>
                }
              />
              <TooltipContent>Translate draft</TooltipContent>
            </Tooltip>
            <InputGroupButton
              variant="default"
              onClick={() => handleSubmit()}
              disabled={!input.trim() || status !== 'ready' || submitting}
            >
              {streaming || submitting ? <Spinner /> : <ArrowUpIcon />}
            </InputGroupButton>
          </InputGroupAddon>
        </InputGroup>
      </form>

      <Dialog open={confirmEnd} onOpenChange={setConfirmEnd}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>End this session?</DialogTitle>
            <DialogDescription>
              The session ends now and your tutor writes a recap plus new review cards from the
              conversation.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmEnd(false)}>
              Keep talking
            </Button>
            <Button variant="destructive" onClick={() => void endSession()} disabled={ending}>
              {ending ? <Spinner data-icon="inline-start" /> : <FlagIcon data-icon="inline-start" />}
              End session
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}
