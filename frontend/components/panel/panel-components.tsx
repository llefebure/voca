'use client'

// Panel components: the visual layer of the tutor's canvas. The side panel
// (split view) while a panel is showing, per-block content rendering, and the
// collapsed chat-thread records of past panels.

import {
  BookOpenIcon,
  CheckIcon,
  ChevronDownIcon,
  InfoIcon,
  ListIcon,
  MessageSquareQuoteIcon,
  PanelRightIcon,
  StickyNoteIcon,
  XIcon,
} from 'lucide-react'
import * as React from 'react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/markdown'
import type { PanelBlock, PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'
import { cn } from 'cn'

const BLOCK_TITLES: Record<PanelBlock['type'], string> = {
  scenario: 'The scene',
  text: 'Reading',
  dialogue: 'Dialogue',
  questions: 'Questions',
  tasks: 'Your tasks',
  word_bank: 'Word bank',
}

const BLOCK_ICONS: Record<PanelBlock['type'], React.ReactNode> = {
  scenario: <InfoIcon className="size-3.5" />,
  text: <BookOpenIcon className="size-3.5" />,
  dialogue: <MessageSquareQuoteIcon className="size-3.5" />,
  questions: <ListIcon className="size-3.5" />,
  tasks: <CheckIcon className="size-3.5" />,
  word_bank: <StickyNoteIcon className="size-3.5" />,
}

/** Normalizes a block for display: escape sequences decode before rendering. */
function displayBlock(block: PanelBlock): PanelBlock {
  return cleanEscapedText(block)
}

const CANVAS_MAX_BLOCKS = 8

/** One content block; each type gets its own distinct visual treatment. */
function PanelBlockView({ block }: { block: PanelBlock }) {
  const display = displayBlock(block)
  switch (display.type) {
    case 'scenario':
      return (
        <Block
          blockType={display.type}
          className="bg-primary/10 border-primary/30"
          title={display.setting}
        >
          <dl className="space-y-1 text-sm">
            <Row label="You" value={display.learner_role} />
            <Row label="Tutor" value={display.tutor_role} />
            <Row label="Goal" value={display.goal} />
          </dl>
        </Block>
      )
    case 'text':
      return (
        <Block blockType={display.type} className="max-h-72 overflow-y-auto" title={display.title ?? undefined}>
          <Markdown className="prose-invert-none">{display.markdown}</Markdown>
        </Block>
      )
    case 'dialogue':
      return (
        <Block blockType={display.type} className="space-y-1.5">
          {display.turns.map((turn, index) => (
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
        <Block blockType={display.type} className="space-y-1">
          <ol className="list-decimal space-y-1 pl-5 text-sm">
            {display.items.map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ol>
        </Block>
      )
    case 'tasks':
      return (
        <Block blockType={display.type} className="space-y-1.5">
          {display.items.map((item, index) => (
            <div key={index} className="text-sm">
              <span className="font-medium">{item.task}</span>
              {item.hint ? <span className="text-muted-foreground"> — {item.hint}</span> : null}
            </div>
          ))}
        </Block>
      )
    case 'word_bank':
      return (
        <Block blockType={display.type} className="flex flex-wrap gap-1.5">
          {display.items.map((item) => (
            <Badge key={item} variant="secondary" className="font-normal">
              {item}
            </Badge>
          ))}
        </Block>
      )
    default:
      return (
        <Block blockType="text" className="text-sm text-muted-foreground">
          (Unsupported panel block)
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
  blockType: PanelBlock['type']
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

/** The full block list of a panel, rendered as one column. */
export function PanelBlocksList({ blocks }: { blocks: PanelBlock[] }) {
  return (
    <div className="space-y-2">
      {(blocks ?? []).slice(0, CANVAS_MAX_BLOCKS).map((block, index) => (
        <PanelBlockView key={index} block={block} />
      ))}
    </div>
  )
}

/**
 * The canvas: the right half of the split view while a panel is showing.
 * The chat keeps flowing on the left; the ✕ dismisses the split view (the
 * panel's chat record stays).
 */
export function PanelCanvas({ panel, onClose }: { panel: PanelInstance; onClose?: () => void }) {
  return (
    <div
      className="flex max-h-full min-h-0 flex-col rounded-xl border border-primary/30 bg-card shadow-sm"
      data-testid="panel-canvas"
    >
      <div className="flex items-center gap-2 border-b border-primary/20 px-4 pt-3 pb-2">
        <PanelRightIcon className="text-primary size-3.5" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{panel.title}</span>
        </div>
        {onClose ? (
          <Button
            variant="ghost"
            size="icon-xs"
            onClick={onClose}
            aria-label="Close panel"
            data-testid="panel-close"
          >
            <XIcon />
          </Button>
        ) : null}
      </div>
      <div className="flex-1 overflow-y-auto px-4 py-3">
        <PanelBlocksList blocks={panel.blocks} />
      </div>
    </div>
  )
}

/**
 * The chat-thread record of a past panel: a collapsed bar (title) that expands
 * to its content. Collapsed by default; the currently-shown panel renders in
 * the canvas instead of a record (the caller decides).
 */
export function PanelRecord({ panel, expanded = false }: { panel: PanelInstance; expanded?: boolean }) {
  const [open, setOpen] = React.useState(expanded)
  return (
    <div className="w-full max-w-[520px]" data-testid="panel-record">
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 rounded-lg border border-primary/20 bg-card/60 px-3 py-2 text-left transition-colors hover:bg-card"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
      >
        <span className="flex min-w-0 items-center gap-2">
          <PanelRightIcon className="text-primary size-3.5 shrink-0" />
          <span className="truncate text-sm font-medium">{panel.title}</span>
        </span>
        <ChevronDownIcon className={`size-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open ? (
        <div className="pt-2">
          <PanelBlocksList blocks={panel.blocks} />
        </div>
      ) : null}
    </div>
  )
}
