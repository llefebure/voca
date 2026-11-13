"use client"

import { Suspense } from "react"
import { Sidebar } from "@/components/sidebar"
import { ThemeToggle } from "@/components/theme-toggle"
import { cn } from "@/lib/utils"

export function DashboardLayout({
  children,
  className,
  title,
}: {
  children: React.ReactNode
  className?: string
  title?: string
}) {
  return (
    // The LanguageProvider lives in the root layout (app/layout.tsx) so pages can
    // read it above their own DashboardLayout.
    <div className="flex h-screen w-full overflow-hidden">
      {/* Sidebar reads usePathname (runtime data); the Suspense boundary lets this
          layout prerender a static shell with a placeholder sidebar. */}
      <Suspense fallback={<aside className="relative h-screen w-64 shrink-0 bg-background border-r" />}>
        <Sidebar />
      </Suspense>
      <div className="flex flex-1 flex-col overflow-hidden relative">
        <header className="h-14 border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 flex items-center justify-between px-4 shrink-0">
          <div className="flex items-center gap-2">
            {title && <h1 className="text-lg font-semibold">{title}</h1>}
          </div>
          <ThemeToggle />
        </header>
        <main className={cn("flex-1 overflow-auto", className)}>
          {children}
        </main>
      </div>
    </div>
  )
}
