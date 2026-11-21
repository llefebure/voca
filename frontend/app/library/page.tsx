'use client'

import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useRouter } from 'next/navigation'
import { Search, BookOpen, Trash2 } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'
import { useLanguage } from '@/components/language-context'
import { toast } from '@/components/ui/toast'
import {
  Pagination,
  PaginationContent,
  PaginationItem,
  PaginationNext,
  PaginationPrevious,
} from '@/components/ui/pagination'
import { cardStateLabel, dueLabel } from '@/lib/stats'

// 3-column grid, 8 rows — server drives the data, one page at a time.
const PAGE_SIZE = 24

type CardRow = {
  id: string
  type: string
  front: string
  back: string
  source_sentence?: string | null
  next_review: string | null
  // JSONB as it arrives (string or object) — lib/stats parses both shapes.
  fsrs_data: unknown
}

export default function LibraryPage() {
  const [cards, setCards] = useState<CardRow[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)
  // The due-badge clock is taken at fetch time in the effect — never at render
  // (render-time `new Date()` is an unstable value under Next 16 prerendering).
  const [now, setNow] = useState<Date | null>(null)
  // `filter` is the live search-box value; `query` is its debounced, server-side
  // counterpart (search runs in PostgREST, not over the rendered page).
  const [filter, setFilter] = useState('')
  const [query, setQuery] = useState('')
  // Bumped to refetch the current page (after a delete) without changing pages.
  const [refreshKey, setRefreshKey] = useState(0)
  const router = useRouter()
  // Cards belong to their session's language; the library shows the active one.
  const { activeLanguage, loading: languageLoading } = useLanguage()

  // Debounce the search box: the server-side query lags typing by 250ms, and a
  // changed query always resets to the first page of results.
  useEffect(() => {
    const timer = setTimeout(() => {
      setQuery(filter)
      setPage(0)
    }, 250)
    return () => clearTimeout(timer)
  }, [filter])

  useEffect(() => {
    if (languageLoading || !activeLanguage) return
    let cancelled = false
    const offset = page * PAGE_SIZE
    const fetchCards = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/auth')
          return
        }

        // Search is server-side: one or-filter over front/back. `,()*` are
        // special in the or-filter syntax, so strip them from the term.
        const term = query.replace(/[,()*]/g, '')
        let request = supabase
          .from('cards')
          .select('*', { count: 'exact' })
          .eq('user_id', user.id)
          .eq('language', activeLanguage)
        if (term) {
          request = request.or(`front.ilike.%${term}%,back.ilike.%${term}%`)
        }

        const { data, error, count } = await request
          .order('created_at', { ascending: false })
          .range(offset, offset + PAGE_SIZE - 1)

        if (error) throw error
        if (cancelled) return
        // Last-page clamp: the page emptied out (e.g. after deletes) — step
        // back one page so the user never stares at a blank last page.
        if ((data || []).length === 0 && offset > 0) {
          setPage(page - 1)
          return
        }
        setCards(data || [])
        setTotal(count ?? (data || []).length)
        setNow(new Date())
      } catch (error) {
        console.error('Error fetching cards:', error)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    fetchCards()
    return () => {
      cancelled = true
    }
  }, [router, activeLanguage, languageLoading, query, page, refreshKey])

  const handleDelete = async (id: string) => {
    try {
      // RLS refusals and already-deleted rows delete zero rows without error, so
      // a .select('id') round trip confirms the deletion actually happened.
      const { data, error } = await supabase
        .from('cards')
        .delete()
        .eq('id', id)
        .select('id')
      if (error) throw error
      if (!data || data.length === 0) {
        toast({
          title: "Card could not be deleted",
          description: "Please refresh and try again.",
          type: "error",
        })
        return
      }
      // Refetch the current page: totals, page size, and the last-page clamp
      // stay consistent with the server (empty page steps back automatically).
      setRefreshKey((key) => key + 1)
      toast({
        title: "Card Deleted",
        description: "The card has been removed from your library.",
        type: "info",
      })
    } catch (error) {
      toast({
        title: "Delete Failed",
        description: error instanceof Error ? error.message : "Delete failed",
        type: "error",
      })
    }
  }

  const offset = page * PAGE_SIZE
  const canPrev = page > 0
  const canNext = (page + 1) * PAGE_SIZE < total

  return (
    <DashboardLayout title="Card Library">
      <div className="mx-auto max-w-6xl space-y-8 p-4 md:p-8">
        <div className="flex gap-4">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              className="pl-10 rounded-full"
              placeholder="Search your vocabulary..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
            />
          </div>
        </div>

        {loading ? (
          <div className="flex h-64 items-center justify-center text-muted-foreground">Loading your library...</div>
        ) : cards.length === 0 ? (
          <div className="text-center py-20 space-y-4">
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
              <BookOpen className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium">No cards found</h3>
            <p className="text-muted-foreground">Start talking with the tutor to generate review cards!</p>
          </div>
        ) : (
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
              {cards.map((card) => {
                const due = dueLabel(card, now)
                return (
                <Card key={card.id} className="group hover:shadow-md transition-all border-t-2 border-t-transparent hover:border-t-primary">
                  <CardContent className="p-6 space-y-4">
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex items-center gap-1.5">
                        <Badge variant="secondary" className="uppercase tracking-wider text-[10px]">
                          {card.type}
                        </Badge>
                        <Badge variant="outline" className="uppercase tracking-wider text-[10px]">
                          {cardStateLabel(card)}
                        </Badge>
                      </div>
                      <div className="flex items-center gap-1.5">
                        {due && (
                          <Badge
                            variant={due === 'Due now' ? 'destructive' : 'outline'}
                            className="text-[10px]"
                          >
                            {due}
                          </Badge>
                        )}
                        <Button
                          size="icon"
                          variant="ghost"
                          className="h-8 w-8 opacity-0 group-hover:opacity-100 text-muted-foreground hover:text-destructive transition-opacity"
                          onClick={() => {
                            if (confirm('Delete this card?')) {
                              handleDelete(card.id)
                            }
                          }}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </div>
                    <div className="space-y-3">
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Front</p>
                        <p className="text-lg font-semibold leading-tight">{card.front}</p>
                      </div>
                      <div className="space-y-1">
                        <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider">Back</p>
                        <p className="text-lg text-foreground/80">{card.back}</p>
                      </div>
                    </div>
                    {card.source_sentence && (
                      <div className="pt-4 border-t space-y-2">
                        <p className="text-xs italic text-muted-foreground">Context from session:</p>
                        <p className="text-xs text-muted-foreground/80 leading-relaxed line-clamp-2">&quot;{card.source_sentence}&quot;</p>
                      </div>
                    )}
                  </CardContent>
                </Card>
                )
              })}
            </div>
            <div className="flex flex-wrap items-center justify-between gap-4">
              <p className="text-sm text-muted-foreground">
                Showing {offset + 1}&ndash;{offset + cards.length} of {total}
              </p>
              <Pagination className="w-auto justify-end">
                <PaginationContent>
                  <PaginationItem>
                    <PaginationPrevious
                      href="#prev"
                      aria-disabled={!canPrev}
                      className={canPrev ? '' : 'pointer-events-none opacity-50'}
                      onClick={(e) => {
                        e.preventDefault()
                        if (canPrev) setPage(page - 1)
                      }}
                    />
                  </PaginationItem>
                  <PaginationItem>
                    <PaginationNext
                      href="#next"
                      aria-disabled={!canNext}
                      className={canNext ? '' : 'pointer-events-none opacity-50'}
                      onClick={(e) => {
                        e.preventDefault()
                        if (canNext) setPage(page + 1)
                      }}
                    />
                  </PaginationItem>
                </PaginationContent>
              </Pagination>
            </div>
          </>
        )}
      </div>
    </DashboardLayout>
  )
}
