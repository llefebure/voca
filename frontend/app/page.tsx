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
import { DEFAULT_LANGUAGE, languageName } from '@/lib/languages'
import type { ChatDataTypes, LessonInstance } from '@/lib/lesson-events'
import { useLanguage } from '@/components/language-context'
import { useSpeech } from '@/lib/use-speech'
import { DashboardLayout } from '@/components/dashboard-layout'
import { Markdown } from '@/components/markdown'
import { lessonTemplateName } from '@/lib/lesson-templates'
import { LessonMaterial, LessonSummaryCard, ProposalCard } from '@/components/lesson/lesson-components'
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

/** The chat page's message type: text + typed lesson data parts. */
export type VocaUIMessage = UIMessage<unknown, ChatDataTypes>

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
  const [acceptingLessonId, setAcceptingLessonId] = React.useState<string | null>(null)
  const sessionIdRef = React.useRef<string | null>(null)
  const lastSpokenRef = React.useRef<string | null>(null)
  // Synchronous guard for Enter-key double submits: state alone can lag one render.
  const submittingRef = React.useRef(false)

  function dataPartMessage(
    id: string,
    kind: 'proposal_ready' | 'lesson_started' | 'lesson_completed' | 'lesson_declined',
    data: unknown,
  ): VocaUIMessage {
    return {
      id,
      role: 'assistant',
      parts: [{ type: `data-${kind}`, id: `${kind}-${id}`, data } as VocaUIMessage['parts'][number]],
    }
  }

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
            body: { messages: messages as VocaUIMessage[], sessionId: options.sessionId },
            headers: { Authorization: `Bearer ${session.access_token}` },
          }
        },
      }),
    [],
  )

  const { messages, sendMessage, status, setMessages } = useChat<VocaUIMessage>({
    transport,
    onError: (error) => {
      toast({ title: 'Chat error', description: error.message, type: 'error' })
    },
  })

  const streaming = status === 'streaming' || status === 'submitted'

  // The lesson state lives in the message list: the last event of each kind wins.
  // Works identically for live streams and restored transcript replays.
  const { activeLesson, pendingProposal } = React.useMemo(() => {
    let active: LessonInstance | null = null
    let pending: LessonInstance | null = null
    let lastSummary: LessonInstance | null = null
    for (const message of messages) {
      for (const part of message.parts) {
        if (part.type === 'data-proposal_ready') {
          pending = part.data.lesson
        } else if (part.type === 'data-lesson_started') {
          active = part.data.lesson
          pending = null
        } else if (part.type === 'data-lesson_completed') {
          active = null
          lastSummary = part.data.lesson
        } else if (part.type === 'data-lesson_declined') {
          if (pending?.id === part.data.lesson_id) pending = null
        }
      }
    }
    return { activeLesson: active, pendingProposal: pending, lastSummary }
  }, [messages])

  // The lesson banner in the header derives straight from that state.
  const phaseLine = pendingProposal
    ? 'Lesson proposed — check the card'
    : activeLesson
      ? `Lesson: ${activeLesson.spec.title}`
      : 'Practice speaking with your conversation partner.'

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
    return data.session_id
  }

  // Continue an open session (History's Continue button links /?session=<id>): the
  // ONLY restore path — nothing auto-resumes on load or toggle. Verifies ownership
  // and open status under RLS, and replays the transcript (including lesson event
  // rows) so the conversation and its lesson state continue seamlessly.
  React.useEffect(() => {
    if (!continueSessionId) return
    let cancelled = false
    void (async () => {
      try {
        const { data: sessionRow } = await supabase
          .from('sessions')
          .select('id, status, lessons')
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
          .select('speaker, text, payload')
          .eq('session_id', sessionRow.id)
          .order('created_at')

        if (cancelled) return
        // Lesson state replays from the persisted payload rows (below) — the
        // derived-state effect walks the messages, as it does for live streams.
        sessionIdRef.current = sessionRow.id
        setSessionId(sessionRow.id)
        const restored: VocaUIMessage[] = []
        for (const [index, line] of (transcript ?? []).entries()) {
          const payload = (line as { payload?: { kind?: string; data?: unknown } }).payload
          if (payload?.kind) {
            const data = payload.data
            if (payload.kind === 'lesson_declined') {
              restored.push(dataPartMessage(`restored-declined-${index}`, 'lesson_declined', data))
            } else if (
              payload.kind === 'proposal_ready' ||
              payload.kind === 'lesson_started' ||
              payload.kind === 'lesson_completed'
            ) {
              restored.push(dataPartMessage(`restored-${payload.kind}-${index}`, payload.kind, data))
            }
            continue
          }
          restored.push({
            id: `restored-${index}`,
            role: line.speaker === 'user' ? ('user' as const) : ('assistant' as const),
            parts: [{ type: 'text' as const, text: line.text }],
          })
        }
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
    // The first message awaits /sessions/start before the transport flips `status`
    // out of `ready` and the input clears, so `status` alone lets a second quick
    // Enter double-submit (and could start a duplicate session). Flip the guard
    // synchronously before that window opens.
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

  /** Accept the pending proposal: POST accept and stream the opener into the chat. */
  async function acceptLesson() {
    const lesson = pendingProposal
    if (!lesson || !sessionIdRef.current || acceptingLessonId) return
    setAcceptingLessonId(lesson.id)
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession()
      if (!session?.access_token) {
        throw new Error('Your session has expired. Please sign in again.')
      }
      const response = await fetch(`${BACKEND_URL}/sessions/lessons/accept`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionIdRef.current }),
      })
      if (!response.ok || !response.body) throw new Error('Failed to start the lesson')

      const openerId = crypto.randomUUID()
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      const upsertOpener = (kind: 'ensure' | 'text', text = '') => {
        setMessages((prev) => {
          const last = prev[prev.length - 1]
          if (last?.id === openerId) {
            const textPart =
              last.parts.find((part) => part.type === 'text') ?? ({ type: 'text', text: '' } as const)
            return [
              ...prev.slice(0, -1),
              {
                ...last,
                parts: [
                  ...last.parts.filter((part) => part.type !== 'text'),
                  { type: 'text' as const, text: (textPart as { text: string }).text + text },
                ],
              },
            ]
          }
          const initial: VocaUIMessage = {
            id: openerId,
            role: 'assistant',
            parts: [
              {
                type: 'data-lesson_started',
                id: `data-${openerId}`,
                data: { lesson },
              } as VocaUIMessage['parts'][number],
              { type: 'text' as const, text: text },
            ],
          }
          return [...prev, initial]
        })
      }

      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        let boundary = buffer.indexOf('\n\n')
        while (boundary !== -1) {
          const frame = buffer.slice(0, boundary)
          buffer = buffer.slice(boundary + 2)
          boundary = buffer.indexOf('\n\n')
          const line = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          try {
            const event = JSON.parse(line.slice('data:'.length))
            if (event.type === 'event' && event.kind === 'lesson_started') {
              upsertOpener('ensure')
            } else if (event.type === 'delta' && typeof event.text === 'string') {
              upsertOpener('text', event.text)
            }
            // `status`/`error`/`done` frames: ignore (accept errors toast on !ok).
          } catch {
            // Non-JSON SSE frame.
          }
        }
      }
    } catch (error) {
      toast({
        title: 'Could not start the lesson',
        description: error instanceof Error ? error.message : 'Failed to start the lesson',
        type: 'error',
      })
    } finally {
      setAcceptingLessonId(null)
    }
  }

  async function declineLesson() {
    const lesson = pendingProposal
    if (!lesson || !sessionIdRef.current) return
    try {
      const {
        data: { session },
      } = await supabase.auth.getSession()
      const response = await fetch(`${BACKEND_URL}/sessions/lessons/decline`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session?.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: sessionIdRef.current }),
      })
      if (!response.ok) throw new Error('Failed to decline')
    } catch (error) {
      toast({
        title: 'Error',
        description: error instanceof Error ? error.message : 'Failed to decline',
        type: 'error',
      })
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
    setMessages([])
  }

  async function endSession() {
    const currentSessionId = sessionIdRef.current
    if (!currentSessionId || ending) return
    setEnding(true)
    try {
      stop()
      // Archive the conversation immediately: from this moment the chat screen
      // must look like an empty state however the request plays out — the recap
      // redirect only lands when the analyst finishes, and navigating away
      // before that must never resurrect the conversation (or its dialog).
      sessionIdRef.current = null
      lastSpokenRef.current = null
      setSessionId(null)
      setMessages([])
      setInput('')
      const {
        data: { session },
      } = await supabase.auth.getSession()
      const response = await fetch(`${BACKEND_URL}/sessions/end`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${session?.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ session_id: currentSessionId }),
      })
      // 409 means the session was already ended (e.g. double click) — treat it
      // as success and still clear the page.
      if (!response.ok && response.status !== 409) {
        throw new Error('Failed to end the session')
      }
      // Close the dialog on every path: an open modal has no meaning once the
      // session is archived, and a lingering one would dead-end (no session
      // left to end). The recap navigation completes this.
      setConfirmEnd(false)
      router.push(`/recap/${currentSessionId}`)
    } catch (error) {
      setConfirmEnd(false)
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
          <div className="font-medium">
            {languageName(targetLanguage)} Session
            {activeLesson ? (
              <span className="text-muted-foreground">
                {' '}
                · {lessonTemplateName(activeLesson.spec.template)}
              </span>
            ) : null}
          </div>
          <div className="text-sm text-muted-foreground">{phaseLine}</div>
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
                Start a conversation in {languageName(targetLanguage)} — chat casually, and Voca
                will offer a structured lesson when the time feels right.
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
                            <div className="flex flex-col items-start gap-2">
                              {message.parts.map((part, partIndex) => {
                                if (part.type === 'text') {
                                  const text = part.text
                                  if (isUser && !text.trim()) return null
                                  return (
                                    <React.Fragment key={`text-${partIndex}`}>
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
                                                    onClick={() =>
                                                      void speak(message.id, text, targetLanguage)
                                                    }
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
                                    </React.Fragment>
                                  )
                                }
                                if (part.type === 'data-proposal_ready') {
                                  const lesson = part.data.lesson
                                  if (lesson.id !== pendingProposal?.id) return null
                                  return (
                                    <ProposalCard
                                      key={`proposal-${lesson.id}`}
                                      lesson={lesson}
                                      onAccept={acceptLesson}
                                      onDecline={declineLesson}
                                      busy={acceptingLessonId === lesson.id}
                                    />
                                  )
                                }
                                if (part.type === 'data-lesson_started') {
                                  const lesson = part.data.lesson
                                  if (lesson.id !== activeLesson?.id) return null
                                  return <LessonMaterial key={`lesson-${lesson.id}`} lesson={lesson} />
                                }
                                if (part.type === 'data-lesson_completed') {
                                  return (
                                    <LessonSummaryCard
                                      key={`summary-${part.data.lesson.id}`}
                                      lesson={part.data.lesson}
                                    />
                                  )
                                }
                                // `data-status` parts render via streamingStatusChip.
                                return null
                              })}
                            </div>
                          </MessageContent>
                        </Message>
                      </MessageScrollerItem>
                    )
                  })}
                  {streamingStatusChip(messages, streaming) !== null && (
                    <MessageScrollerItem messageId="thinking">
                      <Message align="start">
                        <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>
                        <MessageContent>
                          <MessageHeader>Voca</MessageHeader>
                          <Bubble variant="muted" align="start">
                            <BubbleContent>
                              <span className="shimmer">
                                {streamingStatusChip(messages, streaming)}
                              </span>
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
          <InputGroupAddon align="block-end" className="justify-end">
            {/* Ending is the step people miss: a red stop trigger right next to
                the send button, only while a session is open and the tutor is
                quiet (never during submit/stream). */}
            {sessionId && !streaming && (
              <Tooltip>
                <TooltipTrigger
                  render={
                    <InputGroupButton
                      variant="ghost"
                      size="icon-sm"
                      onClick={() => setConfirmEnd(true)}
                      disabled={submitting}
                      aria-label="End session & recap"
                    >
                      <SquareIcon className="text-destructive" />
                    </InputGroupButton>
                  }
                />
                <TooltipContent>End session &amp; recap</TooltipContent>
              </Tooltip>
            )}
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

/** Transient status chip: the latest data-status of the streaming message, pre-text. */
function streamingStatusChip(messages: VocaUIMessage[], streaming: boolean): string | null {
  if (!streaming) return null
  const last = messages[messages.length - 1]
  if (!last || last.role === 'user') return null
  if (last.parts.some((part) => part.type === 'text' && part.text.trim())) return null
  const status = [...last.parts].reverse().find((part) => part.type === 'data-status')
  if (status && status.type === 'data-status') return status.data.text
  return 'Thinking…'
}
