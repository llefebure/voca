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
import {
  LessonThreadBlock,
  MaterialBlocksList,
  ProposalCard,
} from '@/components/lesson/lesson-components'
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

type ChatStatus = 'submitted' | 'streaming' | 'ready' | 'error'

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

  /** Ordered render positions with the lesson (if any) each part belongs to. */
  const { entries, lessonTimeline } = React.useMemo(() => {
    type WalkEntry = {
      message: VocaUIMessage
      messageIndex: number
      partIndex: number
      part: VocaUIMessage['parts'][number]
      lessonId: string | null
    }
    const walked: WalkEntry[] = []
    const timeline = new Map<
      string,
      { lesson: LessonInstance; completed: LessonInstance | null; start: number; end: number | null }
    >()
    let insideLesson: string | null = null
    messages.forEach((message, messageIndex) => {
      message.parts.forEach((part, partIndex) => {
        let lessonId: string | null = insideLesson
        if (part.type === 'data-lesson_started') {
          lessonId = part.data.lesson.id
          insideLesson = lessonId
          if (!timeline.has(lessonId)) {
            timeline.set(lessonId, {
              lesson: part.data.lesson,
              completed: null,
              start: walked.length,
              end: null,
            })
          }
        } else if (part.type === 'data-lesson_completed' && insideLesson) {
          lessonId = insideLesson
          const entry = timeline.get(lessonId)
          if (entry) {
            entry.completed = part.data.lesson
            entry.end = walked.length
          }
        }
        walked.push({ message, messageIndex, partIndex, part, lessonId })
      })
      // A `lesson_completed` event ends the lesson mid-message: parts AFTER it in
      // the same message belong to the main thread again.
      const completedHere = message.parts.find((part) => part.type === 'data-lesson_completed')
      if (completedHere && completedHere.type === 'data-lesson_completed') {
        insideLesson = null
      }
    })
    return { entries: walked, lessonTimeline: timeline }
  }, [messages])

  // The lesson state drives the phase banner + split view.
  const { activeLesson, pendingProposal } = React.useMemo(() => {
    let active: LessonInstance | null = null
    let pending: LessonInstance | null = null
    for (const message of messages) {
      for (const part of message.parts) {
        if (part.type === 'data-proposal_ready') {
          pending = part.data.lesson
        } else if (part.type === 'data-lesson_started') {
          active = part.data.lesson
          pending = null
        } else if (part.type === 'data-lesson_completed') {
          active = null
        } else if (part.type === 'data-lesson_declined') {
          if (pending?.id === part.data.lesson_id) pending = null
        }
      }
    }
    return { activeLesson: active, pendingProposal: pending }
  }, [messages])

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
            if (
              payload.kind === 'proposal_ready' ||
              payload.kind === 'lesson_started' ||
              payload.kind === 'lesson_completed' ||
              payload.kind === 'lesson_declined'
            ) {
              restored.push(dataPartMessage(`restored-${payload.kind}-${index}`, payload.kind, payload.data))
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

      const upsertOpener = (ensure: boolean, text = '') => {
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
              upsertOpener(true)
            } else if (event.type === 'delta' && typeof event.text === 'string') {
              upsertOpener(false, event.text)
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

  /** Renderable nodes for one walked entry; null skips it. */
  function renderEntry(
    entry: (typeof entries)[number],
    context: 'main' | 'lesson',
  ): React.ReactNode {
    const { part, message } = entry
    if (part.type === 'text') {
      const text = part.text
      if (!text.trim()) return null
      const isUser = message.role === 'user'
      return (
        <React.Fragment key={`${entry.messageIndex}-${entry.partIndex}`}>
          <Bubble variant={isUser ? 'default' : 'muted'} align={isUser ? 'end' : 'start'}>
            <BubbleContent>{isUser ? text : <Markdown>{text}</Markdown>}</BubbleContent>
          </Bubble>
          {!isUser && (
            <div className="flex w-full items-center gap-1 px-1 opacity-40 transition-opacity group-hover/message:opacity-100 focus-within:opacity-100">
              <Tooltip>
                <TooltipTrigger
                  render={
                    <Button variant="ghost" size="icon-xs" onClick={() => handleTranslate(text)}>
                      <LanguagesIcon />
                    </Button>
                  }
                />
                <TooltipContent>Translate</TooltipContent>
              </Tooltip>
              {speakingId === message.id ? (
                <Tooltip>
                  <TooltipTrigger render={<Button variant="ghost" size="icon-xs" onClick={stop} />}>
                    <SquareIcon />
                  </TooltipTrigger>
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
        </React.Fragment>
      )
    }
    if (part.type === 'data-proposal_ready') {
      if (context !== 'main') return null
      const lesson = part.data.lesson
      if (lesson.id !== pendingProposal?.id) return null // answered historical proposal
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
      if (context !== 'main') return null // the dock holds the lesson while active
      const record = lessonTimeline.get(part.data.lesson.id)
      if (!record) return null
      return (
        <LessonThreadBlock
          key={`lesson-block-${record.lesson.id}`}
          lesson={record.lesson}
          completed={record.completed}
          record={recordNodes(record.lesson.id)}
        />
      )
    }
    if (part.type === 'data-lesson_completed') return null // lives inside the block
    // `data-status` parts render via the chip.
    return null
  }

  /** The chat that happened inside a lesson — read-only, shown in its block. */
  function recordNodes(lessonId: string): React.ReactNode[] {
    const isText = (entry: (typeof entries)[number]) =>
      entry.lessonId === lessonId && entry.part.type === 'text' && (entry.part as { text: string }).text.trim()
    return entries
      .filter(isText)
      .map((entry, index) => {
        const text = (entry.part as { text: string }).text
        return (
          <Bubble
            key={`record-${lessonId}-${entry.messageIndex}-${index}`}
            variant={entry.message.role === 'user' ? 'default' : 'muted'}
            align={entry.message.role === 'user' ? 'end' : 'start'}
          >
            <BubbleContent>
              {entry.message.role === 'user' ? text : <Markdown>{text}</Markdown>}
            </BubbleContent>
          </Bubble>
        )
      })
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
        {activeLesson ? (
          <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 md:grid-cols-[minmax(0,1fr)_400px]">
            <LessonColumn
              entries={entries.filter(
                (entry) =>
                  entry.lessonId === activeLesson.id && !(entry.part.type === 'data-lesson_started'),
              )}
              status={status}
            />
            <LessonPanel lesson={activeLesson} />
          </div>
        ) : messages.length === 0 ? (
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
          <MessageThread
            entries={entries.filter(
              (entry) =>
                entry.part.type === 'data-lesson_started' ? true : entry.lessonId === null,
            )}
            status={status}
            pendingProposalId={pendingProposal?.id}
            acceptingLessonId={acceptingLessonId}
          />
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

  function MessageThread({
    entries: threadEntries,
    ...rest
  }: {
    entries: typeof entries
    status: ChatStatus
    pendingProposalId?: string
    acceptingLessonId: string | null
  }) {
    // Group walked entries per message so every bubble keeps its avatar/header.
    const groups = [] as { message: VocaUIMessage; parts: typeof threadEntries }[]
    for (const entry of threadEntries) {
      const last = groups[groups.length - 1]
      if (last && last.message.id === entry.message.id) last.parts.push(entry)
      else groups.push({ message: entry.message, parts: [entry] })
    }
    const rendered = groups
      .map((group, groupIndex) => {
        const nodes = group.parts.map((entry) => renderEntry(entry, 'main'))
        if (nodes.every((node) => node === null)) return null
        const isUser = group.message.role === 'user'
        return (
          <MessageScrollerItem
            key={`msg-${group.message.id}`}
            messageId={group.message.id}
            scrollAnchor={groupIndex === groups.length - 1 && isUser}
          >
            <Message align={isUser ? 'end' : 'start'}>
              {!isUser && <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>}
              <MessageContent>
                {!isUser && <MessageHeader>Voca</MessageHeader>}
                <div className="flex flex-col items-start gap-2">{nodes}</div>
              </MessageContent>
            </Message>
          </MessageScrollerItem>
        )
      })
      .filter(Boolean)
    const chip = streamingStatusChip(threadEntries as ChipEntry[], rest.status)
    return (
      <div className="flex min-h-0 flex-1 flex-col">
        <MessageScrollerProvider autoScroll>
          <MessageScroller>
            <MessageScrollerViewport>
              <MessageScrollerContent className="gap-6 py-4">
                {rendered}
                {chip !== null && (
                  <MessageScrollerItem messageId="thinking">
                    <Message align="start">
                      <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>
                      <MessageContent>
                        <MessageHeader>Voca</MessageHeader>
                        <Bubble variant="muted" align="start">
                          <BubbleContent>
                            <span className="shimmer">{chip}</span>
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
    )
  }

  /** The left column of the split view: chat messages from within the lesson. */
  function LessonColumn({
    entries: lessonEntries,
    status: chatStatus,
  }: {
    entries: typeof entries
    status: ChatStatus
  }) {
    const items = lessonEntries.map((entry) => {
      const nodes = renderEntry(entry, 'lesson')
      if (nodes === null) return null
      return (
        <MessageScrollerItem
          key={`lesson-${entry.messageIndex}-${entry.partIndex}`}
          messageId={`lp${entry.messageIndex}-p${entry.partIndex}`}
        >
          <Message align={entry.message.role === 'user' ? 'end' : 'start'}>
            {entry.message.role !== 'user' && <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>}
            <MessageContent>
              {entry.message.role !== 'user' && <MessageHeader>Voca</MessageHeader>}
              <div className="flex flex-col items-start gap-2">{nodes}</div>
            </MessageContent>
          </Message>
        </MessageScrollerItem>
      )
    })
    const visible = items.filter(Boolean)
    const chip =
      (chatStatus === 'submitted' || chatStatus === 'streaming') && visible.length === 0
        ? 'Thinking…'
        : null
    return (
      <div className="flex min-h-0 flex-col">
        <MessageScrollerProvider autoScroll>
          <MessageScroller>
            <MessageScrollerViewport>
              <MessageScrollerContent className="gap-4 py-2">
                {visible.length === 0 && chip === null ? (
                  <div className="text-muted-foreground py-6 text-center text-sm">
                    The lesson&apos;s conversation starts here.
                  </div>
                ) : null}
                {visible}
                {chip !== null && (
                  <MessageScrollerItem messageId="thinking-lesson">
                    <Message align="start">
                      <MessageAvatar>{TUTOR_AVATAR}</MessageAvatar>
                      <MessageContent>
                        <MessageHeader>Voca</MessageHeader>
                        <Bubble variant="muted" align="start">
                          <BubbleContent>
                            <span className="shimmer">{chip}</span>
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
    )
  }
}

/** The right panel of the split view: the active lesson's material. */
function LessonPanel({ lesson }: { lesson: LessonInstance }) {
  const spec = lesson.spec
  return (
    <div className="flex max-h-full min-h-0 flex-col rounded-xl border border-primary/30 bg-card shadow-sm md:order-last">
      <div className="flex items-center gap-2 border-b border-primary/20 px-4 pt-3 pb-2">
        <span className="relative flex size-2" aria-hidden>
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary opacity-60" />
          <span className="relative inline-flex size-2 rounded-full bg-primary" />
        </span>
        <span className="text-xs font-medium tracking-wide uppercase text-muted-foreground">
          Lesson in progress · {lessonTemplateName(spec.template)}
          {spec.minutes ? ` · ~${spec.minutes} min` : ''}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <h3 className="text-sm font-medium mb-2">{spec.title}</h3>
        <div className="space-y-2">
          <MaterialBlocksList blocks={lesson.material} />
        </div>
      </div>
    </div>
  )
}


/** Waiting chip for a walked entry stream (submitted + pre-text streaming). */
type ChipEntry = { part: { type: string; text?: string; data?: { text?: string } } }

function streamingStatusChip(threadEntries: ChipEntry[], chatStatus: ChatStatus): string | null {
  const waiting = chatStatus === 'submitted' || chatStatus === 'streaming'
  if (!waiting) return null
  const lastText = [...threadEntries].reverse().find((entry) => entry.part.type === 'text')
  if (!lastText) return 'Thinking…'
  if ((lastText.part.text ?? '').trim()) return null
  const dataStatus = [...threadEntries]
    .reverse()
    .find((entry) => entry.part.type === 'data-status')
  return dataStatus?.part.data?.text ?? 'Thinking…'
}
