'use client'

import ReactMarkdown from 'react-markdown'
import { cn } from '@/lib/utils'

export function Markdown({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      <ReactMarkdown>
        {typeof children === 'string' ? children : String(children ?? '')}
      </ReactMarkdown>
    </div>
  )
}
