'use client'

// Lesson components: the visual layer of the small-talk ⇄ lesson loop. Proposal
// cards, per-block lesson material (each type rendered distinctly — a reading
// passage is a document card, a dialogue is a script with fill-in gaps), and
// the end-of-lesson summary with review-credit marks.

import {
  BookOpenIcon,
  CheckIcon,
  ChevronDownIcon,
  InfoIcon,
  ListIcon,
  MessageSquareQuoteIcon,
  SparklesIcon,
  StarIcon,
  StickyNoteIcon,
} from 'lucide-react'
import * as React from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Markdown } from '@/components/markdown'
import { lessonTemplateBlurb, lessonTemplateName } from '@/lib/lesson-templates'
import type { LessonInstance, MaterialBlock, LessonGrade } from '@/lib/lesson-events'
import { cn } from 'cn'

const BLOCK_TITLES: Record<MaterialBlock['type'], string> = {
  scenario: 'The scene',
  text: 'Reading',
  dialogue: 'Dialogue',
  questions: 'Questions',
  tasks: 'Your tasks',
  word_bank: 'Word bank',
}

const BLOCK_ICONS: Record<MaterialBlock['type'], React.ReactNode> = {
  scenario: <InfoIcon className="size-3.5" />,
  text: <BookOpenIcon className="size-3.5" />,
  dialogue: <MessageSquareQuoteIcon className="size-3.5" />,
  questions: <ListIcon className="size-3.5" />,
  tasks: <CheckIcon className="size-3.5" />,
  word_bank: <StickyNoteIcon className="size-3.5" />,
}

/**
 * The lesson proposal as it waits for the learner's answer: template, objectives
 * and a preview, with Accept / Not-now. Rendered inline in the chat stream.
 */
export function ProposalCard({
  lesson,
  onAccept,
  onDecline,
  busy,
}: {
  lesson: LessonInstance
  onAccept: () => void
  onDecline: () => void
  busy?: boolean
}) {
  const spec = lesson.spec
  return (
    <Card className="border-primary/30 w-full max-w-[520px] shadow-sm" data-testid="proposal-card">
      <CardHeader className="gap-2">
        <div className="flex items-center gap-2">
          <Badge variant="default">{lessonTemplateName(spec.template)}</Badge>
          <span className="text-sm text-muted-foreground">
            {spec.minutes ? `~${spec.minutes} min` : lessonTemplateBlurb(spec.template)}
          </span>
        </div>
        <CardTitle className="text-base">{spec.title}</CardTitle>
        {lesson.reason ? (
          <p className="text-sm text-muted-foreground">{lesson.reason}</p>
        ) : null}
      </CardHeader>
      <CardContent className="space-y-3">
        {spec.objectives && spec.objectives.length > 0 ? (
          <ul className="space-y-1 text-sm">
            {spec.objectives.slice(0, 3).map((objective) => (
              <li key={objective} className="flex items-start gap-1.5">
                <CheckIcon className="text-primary mt-0.5 size-3.5 shrink-0" />
                <span>{objective}</span>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex gap-2">
          <Button size="sm" onClick={onAccept} disabled={busy} data-testid="proposal-accept">
            {busy ? 'Starting…' : "Let's do it"}
          </Button>
          <Button size="sm" variant="outline" onClick={onDecline} disabled={busy} data-testid="proposal-decline">
            Not now
          </Button>
        </div>
      </CardContent>
    </Card>
  )
}

/** One material block; each type gets its own distinct visual treatment. */
function MaterialBlockView({ block }: { block: MaterialBlock }) {
  switch (block.type) {
    case 'scenario':
      return (
        <Block
          blockType={block.type}
          className="bg-primary/10 border-primary/30"
          title={block.setting}
        >
          <dl className="space-y-1 text-sm">
            <Row label="You" value={block.learner_role} />
            <Row label="I am" value={block.tutor_role} />
            <Row label="Goal" value={block.goal} />
          </dl>
        </Block>
      )
    case 'text':
      return (
        <Block blockType={block.type} className="max-h-72 overflow-y-auto" title={block.title ?? undefined}>
          <Markdown className="prose-invert-none">{block.markdown}</Markdown>
        </Block>
      )
    case 'dialogue':
      return (
        <Block blockType={block.type} className="space-y-1.5">
          {block.turns.map((turn, index) => (
            <div key={index} className="text-sm">
              <span className={cn('font-medium', turn.speaker === 'tutor' ? 'text-primary' : 'text-foreground')}>
                {turn.speaker === 'tutor' ? 'Voca' : 'You'}:
              </span>{' '}
              {turn.text ? (
                <span>{turn.text}</span>
              ) : (
                <span className="ml-1 inline-block w-32 rounded-sm border-b border-dashed pb-0.5 font-mono text-xs align-middle text-muted-foreground" data-testid="dialogue-gap" />
              )}
            </div>
          ))}
        </Block>
      )
    case 'questions':
      return (
        <Block blockType={block.type} className="space-y-1">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {block.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </Block>
      )
    case 'tasks':
      return (
        <Block blockType={block.type} className="space-y-1.5">
          {block.items.map((item, index) => (
            <div key={index} className="text-sm">
              <span className="font-medium">{item.task}</span>
              {item.hint ? <span className="text-muted-foreground"> — {item.hint}</span> : null}
            </div>
          ))}
        </Block>
      )
    case 'word_bank':
      return (
        <Block blockType={block.type} className="flex flex-wrap gap-1.5">
          {block.items.map((item) => (
            <Badge key={item} variant="secondary" className="font-normal">
              {item}
            </Badge>
          ))}
        </Block>
      )
    default:
      return (
        <Block blockType="text" className="text-sm text-muted-foreground">
          (Unsupported material block)
        </Block>
      )
  }
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="inline font-medium">{label}: </dt>
      <dd className="inline">{value}</dd>
    </div>
  )
}

function Block({
  blockType,
  title,
  className,
  children,
}: {
  blockType: MaterialBlock['type']
  title?: string
  className?: string
  children: React.ReactNode
}) {
  return (
    <div className={cn('rounded-lg border bg-card/60 p-3', className)} data-block-type={blockType}>
      <div className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs font-medium tracking-wide uppercase">
        {BLOCK_ICONS[blockType]}
        {title ? (
          <span className="normal-case text-foreground">{title}</span>
        ) : (
          <span>{BLOCK_TITLES[blockType]}</span>
        )}
      </div>
      {children}
    </div>
  )
}

/** The full material of a lesson (banner + blocks), rendered as one card. */
export function MaterialBlocksList({ blocks }: { blocks: MaterialBlock[] }) {
  return (
    <div className="space-y-2">
      {(blocks ?? []).map((block, index) => (
        <MaterialBlockView key={index} block={block} />
      ))}
    </div>
  )
}

export function LessonMaterial({ lesson }: { lesson: LessonInstance }) {
  const spec = lesson.spec
  return (
    <Card className="border-primary/30 w-full max-w-[520px] shadow-sm bg-card" data-testid="lesson-material">
      <CardHeader className="gap-1.5 pb-2">
        <div className="flex items-center gap-2">
          <SparklesIcon className="text-primary size-3.5" />
          <span className="text-xs font-medium tracking-wide uppercase text-muted-foreground">
            Lesson · {lessonTemplateName(spec.template)}
            {spec.minutes ? ` · ~${spec.minutes} min` : ''}
          </span>
        </div>
        <CardTitle className="text-base">{spec.title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        <MaterialBlocksList blocks={lesson.material} />
      </CardContent>
    </Card>
  )
}

const OUTCOME_MARKS: Record<string, { mark: string; className: string }> = {
  strong_pass: { mark: '⭐', className: 'text-foreground' },
  pass: { mark: '⭐', className: 'text-foreground' },
  recognition_pass: { mark: '👀', className: 'text-muted-foreground' },
  miss: { mark: '⏸', className: 'text-muted-foreground' },
}

/**
 * The end-of-lesson summary card: what happened plus how each target card went.
 * ⭐ = used correctly in context (the bonus), 👀 = understood it, ⏸ = not touched.
 */
export function LessonSummaryCard({ lesson }: { lesson: LessonInstance }) {
  const summary = lesson.summary
  const grades: LessonGrade[] = lesson.grades ?? []
  const bonusCount = (summary?.bonus_uses ?? []).length
  if (!summary) return null
  return (
    <Card className="w-full max-w-[520px] shadow-sm" data-testid="lesson-summary">
      <CardHeader className="gap-1 pb-2">
        <div className="flex items-center gap-2 text-sm">
          <StarIcon className="size-3.5 text-amber-500" />
          <span className="font-medium">{summary.headline}</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-2 text-sm">
        {bonusCount > 0 ? (
          <div className="flex items-center gap-1.5">
            <Badge variant="secondary">
              ⭐ {bonusCount} bonus {bonusCount === 1 ? 'use' : 'uses'}
            </Badge>
          </div>
        ) : null}
        {grades.length > 0 ? (
          <div className="space-y-0.5">
            {grades.map((grade, index) => {
              const front =
                lesson.target_cards.find((card) => card.id === grade.card_id)?.front ?? grade.card_id
              const marks = OUTCOME_MARKS[grade.outcome] ?? OUTCOME_MARKS.recognition_pass
              return (
                <div key={`${grade.card_id}-${index}`} className="flex items-baseline gap-2">
                  <span aria-hidden>{marks.mark}</span>
                  <span>{front}</span>
                </div>
              )
            })}
          </div>
        ) : null}
        {summary.key_phrases && summary.key_phrases.length > 0 ? (
          <div className="flex flex-wrap gap-1.5">
            {summary.key_phrases.map((phrase) => (
              <Badge key={phrase} variant="secondary" className="font-normal">
                {phrase}
              </Badge>
            ))}
          </div>
        ) : null}
      </CardContent>
    </Card>
  )
}

/**
 * The pinned "in the lesson" dock: while a lesson is active its material lives
 * here, visually distinct from the chat stream below. Collapses naturally away
 * when the lesson completes (the thread keeps a collapsible record instead —
 * see `LessonThreadBlock`).
 */
export function LessonDock({ lesson }: { lesson: LessonInstance }) {
  const spec = lesson.spec
  return (
    <div
      className="w-full max-w-[600px] rounded-xl border border-primary/30 bg-card shadow-sm"
      data-testid="lesson-dock"
    >
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
      <div className="max-h-[45vh] overflow-y-auto px-4 py-3">
        <h3 className="text-sm font-medium mb-2">{spec.title}</h3>
        <MaterialBlocksList blocks={lesson.material} />
      </div>
    </div>
  )
}

/**
 * The chat-thread record of a lesson: a collapsed bar (title · status · bonus
 * count) that expands to the material and, once present, the completion
 * summary. Collapsed while the lesson is docked above; auto-collapses on
 * completion; expandable at any time afterwards.
 */
export function LessonThreadBlock({
  lesson,
  completed,
  active,
}: {
  lesson: LessonInstance
  completed?: LessonInstance | null
  active?: boolean
}) {
  // Collapsed by default: the pinned dock holds the material while the lesson is
  // in progress, so the thread keeps a tappable record that stays put once the
  // lesson completes and the dock goes away.
  const [expanded, setExpanded] = React.useState(false)

  const bonus = (completed?.summary?.bonus_uses ?? []).length
  const status = active ? 'in progress' : completed ? 'completed' : 'started'
  return (
    <div className="w-full max-w-[520px]" data-testid="lesson-thread-block" data-status={status}>
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-primary/20 bg-card/60 px-3 py-2 text-left transition-colors hover:bg-card"
        onClick={() => setExpanded((prev) => !prev)}
        aria-expanded={expanded}
      >
        <span className="flex min-w-0 items-center gap-2">
          <Badge variant="secondary">{lessonTemplateName(lesson.spec.template)}</Badge>
          <span className="truncate text-sm font-medium">{lesson.spec.title}</span>
        </span>
        <span className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
          {bonus > 0 ? <span>⭐ {bonus}</span> : null}
          <span>{status}</span>
          <ChevronDownIcon
            className={`size-4 transition-transform ${expanded ? 'rotate-180' : ''}`}
          />
        </span>
      </button>
      {expanded ? (
        <div className="space-y-2 pt-2">
          <LessonMaterial lesson={lesson} />
          {completed?.summary ? <LessonSummaryCard lesson={completed} /> : null}
        </div>
      ) : null}
    </div>
  )
}
