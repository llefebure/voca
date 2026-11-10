'use client'

import * as React from 'react'
import { useRouter } from 'next/navigation'
import { useChat } from '@ai-sdk/react'
import { DefaultChatTransport } from 'ai'
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

export default function ChatPage() {
  const router = useRouter()
  const { muted, toggleMuted, speakingId, speak, stop } = useSpeech()
  const [input, setInput] = React.useState('')
  const [ending, setEnding] = React.useState(false)
  const [confirmEnd, setConfirmEnd] = React.useState(false)
  const [sessionId, setSessionId] = React.useState<string | null>(null)
  const sessionIdRef = React.useRef<string | null>(null)
  const lastSpokenRef = React.useRef<string | null>(null)

  // Auth check
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
      }
    }
    checkUser()
  }, [router])

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

  async function handleSubmit(event?: React.FormEvent) {
    event?.preventDefault()
    const text = input.trim()
    if (!text || status !== 'ready') return
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
    void speak(last.id, text)
  }, [messages, muted, speak, status])

  function handleTranslate(text: string) {
    void (async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/translate`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text, source_lang: 'es', target_lang: 'en' }),
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

  function startNewSession() {
    stop()
    sessionIdRef.current = null
    lastSpokenRef.current = null
    setMessages([])
  }

  function endSession() {
    void (async () => {
      const sessionId = sessionIdRef.current
      if (!sessionId || ending) return
      setEnding(true)
      try {
        stop()
        const {
          data: { session },
        } = await supabase.auth.getSession()
        const response = await fetch(
          `${BACKEND_URL}/sessions/end?session_id=${encodeURIComponent(sessionId)}`,
          { method: 'POST', headers: { Authorization: `Bearer ${session?.access_token}` } },
        )
        if (!response.ok) throw new Error('Failed to end the session')
        sessionIdRef.current = null
        lastSpokenRef.current = null
        router.push(`/recap/${sessionId}`)
      } catch (error) {
        toast({
          title: 'Error',
          description: error instanceof Error ? error.message : 'Failed to end the session',
          type: 'error',
        })
      } finally {
        setEnding(false)
      }
    })()
  }

  return (
    <DashboardLayout title="AI Tutor">
      <div className="relative flex h-full w-full flex-col">
        <div className="flex items-start justify-between gap-4 px-8 pt-6 pb-4">
          <div className="flex flex-col gap-1">
            <div className="font-medium">Spanish Session</div>
            <div className="text-sm text-muted-foreground">
              Practice your conversation with the AI Tutor.
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
                  Start a conversation in Spanish to improve your fluency.
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
                                            onClick={() => void speak(message.id, text)}
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
                                <span className="shimmer">Pensando…</span>
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
              placeholder="Type your message in Spanish…"
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
                disabled={!input.trim() || status !== 'ready'}
              >
                {streaming ? <Spinner /> : <ArrowUpIcon />}
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
              <Button variant="destructive" onClick={endSession} disabled={ending}>
                {ending ? <Spinner data-icon="inline-start" /> : <FlagIcon data-icon="inline-start" />}
                End session
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </DashboardLayout>
  )
}
