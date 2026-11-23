'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { cn } from '@/lib/utils'

export function Markdown({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("prose prose-sm dark:prose-invert max-w-none", className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}>
        {typeof children === 'string' ? children : String(children ?? '')}
      </ReactMarkdown>
    </div>
  )
}
