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
import type { ChatDataTypes, PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'
import { useLanguage } from '@/components/language-context'
import { useSpeech } from '@/lib/use-speech'
import { DashboardLayout } from '@/components/dashboard-layout'
import { Markdown } from '@/components/markdown'
import { PanelPane } from '@/components/panel/panel-components'
import { cn } from 'cn'
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

/** The chat page's message type: text + typed panel data parts. */
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

  /* Keying on the language resets all chat state when the user toggles languages:
     the previous conversation stays open in History under its own language (the
     same semantics as "New session") — nothing is auto-resumed after a toggle.
     The continue param only reaches the view once the context has resolved. */
  return (
    <ChatView
      key={targetLanguage}
      targetLanguage={targetLanguage}
      continueSessionId={languageLoading ? null : continueSessionId}
    />
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
  // Panel pane UI state (which tab, folded or not). It carries a walk
  // sequence: user choices hold only until the next panel event, which takes
  // the derived state back over (a new show expands + focuses, a tutor fold
  // collapses).
  const [panelUi, setPanelUi] = React.useState<{
    seq: number
    collapsed?: boolean
    activeIndex?: number
  }>({ seq: -1 })
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

  /** Ordered walked entries (one per message part) + the panels shown so far. */
  const entries = React.useMemo(() => {
    const walked: {
      message: VocaUIMessage
      messageIndex: number
      partIndex: number
      part: VocaUIMessage['parts'][number]
    }[] = []
    messages.forEach((message, messageIndex) => {
      message.parts.forEach((part, partIndex) => {
        walked.push({ message, messageIndex, partIndex, part })
      })
    })
    return walked
  }, [messages])

  /**
   * The panel drive, additive: every `panel_shown` becomes a tab (a re-show of
   * the same id replaces that tab's content); `panel_hidden` folds the pane
   * away (the learner can reopen). `seq` bumps on each panel event so user UI
   * choices can be invalidated when the tutor moves the panel.
   */
  const panelWalk = React.useMemo(() => {
    const panels: PanelInstance[] = []
    const indexOf = new Map<string, number>()
    let focusId: string | null = null
    let tutorCollapsed = false
    let seq = 0
    for (const { part } of entries) {
      if (part.type === 'data-panel_shown') {
        const panel = cleanEscapedText(part.data.panel)
        if (typeof panel.markdown !== 'string') continue // legacy content shapes: skip
        const existingIndex = indexOf.get(panel.id)
        if (existingIndex === undefined) {
          indexOf.set(panel.id, panels.length)
          panels.push(panel)
        } else {
          panels[existingIndex] = panel // same id re-shown: replace that tab's content
        }
        focusId = panel.id
        tutorCollapsed = false // a (re)show expands the pane
        seq += 1
      } else if (part.type === 'data-panel_hidden') {
        tutorCollapsed = true // the tutor folds the pane away
        seq += 1
      }
    }
    return { panels, focusId, tutorCollapsed, seq }
  }, [entries])

  // Effective pane state: tutor-derived unless the user picked something for
  // THIS walk state (their choice holds until the next panel event).
  const ui = panelUi.seq === panelWalk.seq ? panelUi : { seq: panelWalk.seq }
  const panelCollapsed = ui.collapsed ?? panelWalk.tutorCollapsed
  const panelActiveIndex = ui.activeIndex ?? Math.min(
    Math.max(panelWalk.panels.findIndex((panel) => panel.id === panelWalk.focusId), 0),
    Math.max(panelWalk.panels.length - 1, 0),
  )
  function setPanelPaneUi(update: { collapsed?: boolean; activeIndex?: number }) {
    setPanelUi({ seq: panelWalk.seq, ...update })
  }
  const hasPanels = panelWalk.panels.length > 0

  /** Renderable node for one walked part; null skips it (empty/absorbed parts). */
  function renderEntry(entry: (typeof entries)[number]): React.ReactNode {
    const { part, message, messageIndex, partIndex } = entry
    if (part.type === 'text') {
      const text = part.text
      if (!text.trim()) return null
      const isUser = message.role === 'user'
      return (
        <React.Fragment key={`${messageIndex}-${partIndex}`}>
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
    if (part.type === 'data-panel_shown' || part.type === 'data-panel_hidden') {
      // Absorbed by the panel pane — artifacts never render inline in the log.
      return null
    }
    // `data-status` parts render via the chip.
    return null
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
    return data.session_id
  }

  function dataPartMessage(
    id: string,
    kind: 'panel_shown' | 'panel_hidden',
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
  // and open status under RLS, and replays the transcript (including panel event
  // rows) so the conversation and its canvas continue seamlessly.
  React.useEffect(() => {
    if (!continueSessionId) return
    let cancelled = false
    void (async () => {
      try {
        const { data: sessionRow } = await supabase
          .from('sessions')
          .select('id, status')
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
        sessionIdRef.current = sessionRow.id
        setSessionId(sessionRow.id)
        const restored: VocaUIMessage[] = []
        for (const [index, line] of (transcript ?? []).entries()) {
          const payload = (line as { payload?: { kind?: string; data?: unknown } }).payload
          if (payload?.kind) {
            if (payload.kind === 'panel_shown' || payload.kind === 'panel_hidden') {
              const data = cleanEscapedText(payload.data)
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
        setPanelUi({ seq: -1 }) // the replayed walk drives the pane afresh
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
    setPanelUi({ seq: -1 })
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
      setPanelUi({ seq: -1 })
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

  return (
    <DashboardLayout
      title="Conversation Tutor"
      actions={
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
      }
    >
      <div className="relative flex h-full w-full flex-col">
      {/* The content region splits into two flush rectangles whenever panel
          artifacts exist: the chat pane and the canvas pane together fill the
          full rectangle (divider line between them). The pane is additive
          (tabs per artifact) and folds to a rail at the user's or the tutor's
          request. */}
      <div className="flex min-h-0 flex-1 flex-col md:flex-row">
        {hasPanels ? (
          <>
            <div className="flex min-h-0 flex-1 flex-col px-8">
              <MessageThread entries={entries} status={status} />
            </div>
            <div
              className={cn(
                'flex w-full shrink-0 flex-col border-t md:h-full md:border-t-0 md:border-l',
                panelCollapsed ? 'w-11' : 'w-full md:w-[420px]',
              )}
            >
              <PanelPane
                panels={panelWalk.panels}
                activeIndex={panelActiveIndex}
                onSelect={(index) => setPanelPaneUi({ activeIndex: index })}
                collapsed={panelCollapsed}
                onToggleCollapse={() => setPanelPaneUi({ collapsed: !panelCollapsed })}
              />
            </div>
          </>
        ) : messages.length === 0 ? (
          <div className="flex min-h-0 flex-1 flex-col px-8">
            <Empty className="flex-1">
              <EmptyHeader>
                <EmptyMedia variant="icon">
                <LanguagesIcon />
              </EmptyMedia>
              <EmptyTitle>Ready to practice?</EmptyTitle>
              <EmptyDescription>
                Start a conversation in {languageName(targetLanguage)} — chat casually, and your
                tutor will put menus, scripts, or exercises on the side panel whenever they help.
              </EmptyDescription>
              </EmptyHeader>
            </Empty>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col px-8">
            <MessageThread entries={entries} status={status} />
          </div>
        )}
      </div>

      <form onSubmit={handleSubmit} className="border-t px-8 pt-3 pb-6">
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
            {/* Voice on/off lives with the other composition controls. */}
            <Tooltip>
              <TooltipTrigger
                render={
                  <InputGroupButton
                    variant="ghost"
                    size="icon-sm"
                    onClick={toggleMuted}
                    aria-label={muted ? 'Speech is muted' : 'Speech is on'}
                  >
                    {muted ? <VolumeXIcon /> : <Volume2Icon />}
                  </InputGroupButton>
                }
              />
              <TooltipContent>{muted ? 'Speech is muted' : 'Speech is on'}</TooltipContent>
            </Tooltip>
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
    </DashboardLayout>
  )

  function MessageThread({ entries: threadEntries, status }: { entries: typeof entries; status: ChatStatus }) {
    // Group walked entries per message so every bubble keeps its avatar/header.
    const groups = [] as { message: VocaUIMessage; parts: typeof threadEntries }[]
    for (const entry of threadEntries) {
      const last = groups[groups.length - 1]
      if (last && last.message.id === entry.message.id) last.parts.push(entry)
      else groups.push({ message: entry.message, parts: [entry] })
    }
    const chip = streamingStatusChip(groups, status)
    const rendered = groups
      .map((group, groupIndex) => {
        const nodes = group.parts.map((entry) => renderEntry(entry))
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
}

type MessageGroup = { message: VocaUIMessage; parts: { part: VocaUIMessage['parts'][number] }[] }

/**
 * The waiting chip covers a still-empty assistant turn — and nothing else:
 * once the newest assistant message carries rendered content (text or a
 * panel), any tool chip is stale and yields. Before streaming starts, it's
 * just "Thinking…".
 */
function streamingStatusChip(groups: MessageGroup[], chatStatus: ChatStatus): string | null {
  if (chatStatus !== 'submitted' && chatStatus !== 'streaming') return null
  const last = groups[groups.length - 1]
  if (!last || last.message.role !== 'assistant') return 'Thinking…'
  const hasContent = last.parts.some(
    (entry) =>
      (entry.part.type === 'text' && (entry.part as { text: string }).text.trim()) ||
      entry.part.type === 'data-panel_shown',
  )
  if (hasContent) return null
  const status = [...last.parts]
    .reverse()
    .find((entry) => entry.part.type === 'data-status')
  return ((status?.part as { data?: { text?: string } } | undefined)?.data?.text ?? '')
    ? (status?.part as { data: { text: string } }).data.text
    : 'Thinking…'
}
