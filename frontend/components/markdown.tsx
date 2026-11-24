'use client'

import ReactMarkdown from 'react-markdown'
import remarkBreaks from 'remark-breaks'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

/**
 * Renders markdown. `breaks` treats single newlines as line breaks (panels:
 * the tutor writes line-per-item content that CommonMark would otherwise
 * collapse); chat bubbles keep standard CommonMark.
 */
export function Markdown({
  children,
  className,
  breaks = false,
}: {
  children: React.ReactNode
  className?: string
  breaks?: boolean
}) {
  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      <ReactMarkdown remarkPlugins={breaks ? [remarkGfm, remarkBreaks] : [remarkGfm]}>
        {typeof children === 'string' ? children : String(children ?? '')}
      </ReactMarkdown>
    </div>
  )
}
