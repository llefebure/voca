'use client'

// Panel components: the visual layer of the tutor's canvas. The side pane is
// additive: every artifact becomes a tab (newest focused), and it can fold
// away to a slim rail — the learner reopens it from there. Content is plain
// markdown, composed by the tutor.

import { ChevronLeftIcon, ChevronRightIcon, PanelRightIcon } from 'lucide-react'
import * as React from 'react'

import { Markdown } from '@/components/markdown'
import type { PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'
import { cn } from '@/lib/utils'

/** Normalizes a panel for display: escape sequences decode before rendering. */
export function displayPanel(panel: PanelInstance): PanelInstance {
  return cleanEscapedText(panel)
}

/**
 * The side pane of the split view. Expanded: a tab bar (one tab per
 * generated artifact, shown only when there are several) atop the focused
 * artifact's markdown, with a fold button. Collapsed: a slim rail with the
 * focused artifact's title on its side; clicking reopens.
 */
export function PanelPane({
  panels,
  activeIndex,
  onSelect,
  collapsed,
  onToggleCollapse,
}: {
  panels: PanelInstance[]
  activeIndex: number
  onSelect: (index: number) => void
  collapsed: boolean
  onToggleCollapse: () => void
}) {
  const active = panels[Math.min(Math.max(activeIndex, 0), panels.length - 1)]
  return (
    <div
      className="flex min-h-0 flex-1 flex-col bg-card"
      data-testid="panel-pane"
      data-collapsed={collapsed ? 'true' : 'false'}
    >
      {collapsed ? (
        // The folded rail: full-height, click to reopen.
        <button
          type="button"
          className="flex h-full w-11 flex-col items-center gap-3 py-3 text-muted-foreground transition-colors hover:text-foreground"
          onClick={onToggleCollapse}
          aria-label="Reopen panel"
          data-testid="panel-rail"
        >
          <ChevronLeftIcon className="size-4" />
          <PanelRightIcon className="size-4 shrink-0" />
          <span
            className="text-xs font-medium tracking-wide"
            style={{ writingMode: 'vertical-rl' }}
          >
            {active?.title ?? 'Panel'}
            {panels.length > 1 ? ` (${panels.length})` : ''}
          </span>
        </button>
      ) : (
        <>
          <div className="flex items-center gap-1 border-b py-2.5 pl-4 pr-2">
            {panels.length > 1 ? (
              <div className="flex min-w-0 flex-1 flex-wrap gap-1" role="tablist" aria-label="Panel artifacts">
                {panels.map((panel, index) => (
                  <button
                    key={panel.id}
                    type="button"
                    role="tab"
                    aria-selected={index === activeIndex}
                    data-testid={`panel-tab-${index}`}
                    className={cn(
                      'flex items-center gap-1.5 rounded-md px-2.5 py-1 text-xs font-medium transition-colors',
                      index === activeIndex
                        ? 'bg-primary text-primary-foreground'
                        : 'text-muted-foreground hover:text-foreground',
                    )}
                    onClick={() => onSelect(index)}
                  >
                    <PanelRightIcon className="size-3 shrink-0" />
                    <span className="max-w-[170px] truncate">{panel.title}</span>
                  </button>
                ))}
              </div>
            ) : (
              <div className="flex min-w-0 flex-1 items-center gap-1.5 text-xs font-medium tracking-wide text-muted-foreground uppercase">
                <PanelRightIcon className="size-3.5 shrink-0" />
                <span className="truncate">{active?.title}</span>
              </div>
            )}
            <button
              type="button"
              className="rounded-md p-1.5 text-muted-foreground transition-colors hover:text-foreground"
              onClick={onToggleCollapse}
              aria-label="Fold panel to the side"
              data-testid="panel-collapse"
            >
              <ChevronRightIcon className="size-4" />
            </button>
          </div>
          {active ? (
            <div className="min-h-0 flex-1 overflow-y-auto px-4 py-3">
              <Markdown breaks className="prose-invert-none">{displayPanel(active).markdown}</Markdown>
            </div>
          ) : null}
        </>
      )}
    </div>
  )
}
