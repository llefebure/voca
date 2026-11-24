'use client'

// Panel components: the visual layer of the tutor's canvas. The side panel
// (split view) while a panel is showing, plus the collapsed chat-thread
// records of past panels. Content is plain markdown, composed by the tutor.

import { ChevronDownIcon, PanelRightIcon, XIcon } from 'lucide-react'
import * as React from 'react'

import { Button } from '@/components/ui/button'
import { Markdown } from '@/components/markdown'
import type { PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'

/** Normalizes a panel for display: escape sequences decode before rendering. */
export function displayPanel(panel: PanelInstance): PanelInstance {
  return cleanEscapedText(panel)
}

/**
 * The canvas: the right half of the split view while a panel is showing.
 * The chat keeps flowing on the left; the ✕ dismisses the split view (the
 * panel's chat record stays).
 */
export function PanelCanvas({ panel, onClose }: { panel: PanelInstance; onClose?: () => void }) {
  const display = displayPanel(panel)
  return (
    <div
      className="flex max-h-full min-h-0 flex-col rounded-xl border border-primary/30 bg-card shadow-sm"
      data-testid="panel-canvas"
    >
      <div className="flex items-center gap-2 border-b border-primary/20 px-4 pt-3 pb-2">
        <PanelRightIcon className="text-primary size-3.5" />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm font-medium">{display.title}</span>
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
        <Markdown className="prose-invert-none">{display.markdown}</Markdown>
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
  const display = displayPanel(panel)
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
          <span className="truncate text-sm font-medium">{display.title}</span>
        </span>
        <ChevronDownIcon className={`size-4 shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>
      {open ? (
        <div className="pt-2">
          <Markdown className="prose-invert-none">{display.markdown}</Markdown>
        </div>
      ) : null}
    </div>
  )
}
