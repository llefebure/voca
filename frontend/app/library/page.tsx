'use client'

import { useState, useEffect } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useRouter } from 'next/navigation'
import { Search, BookOpen, GraduationCap, Trash2 } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'
import { toast } from '@/components/ui/toast'

type CardRow = {
  id: string
  type: string
  front: string
  back: string
  source_sentence?: string | null
}

export default function LibraryPage() {
  const [cards, setCards] = useState<CardRow[]>([])
  const [filter, setFilter] = useState('')
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const fetchCards = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/auth')
          return
        }

        const { data, error } = await supabase
          .from('cards')
          .select('*')
          .eq('user_id', user.id)
          .order('created_at', { ascending: false })

        if (error) throw error
        setCards(data || [])
      } catch (error) {
        console.error('Error fetching cards:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchCards()
  }, [router])

  const filteredCards = cards.filter(card => 
    card.front.toLowerCase().includes(filter.toLowerCase()) || 
    card.back.toLowerCase().includes(filter.toLowerCase())
  )

  const handleDelete = async (id: string) => {
    try {
      const { error } = await supabase.from('cards').delete().eq('id', id)
      if (error) throw error
      setCards(cards.filter(c => c.id !== id))
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

  return (
    <DashboardLayout title="Card Library">
      <div className="mx-auto max-w-6xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Title is in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Start Practicing
          </Button>
        </div>

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
          <div className="flex gap-2">
            <Button variant="outline" className="hidden md:flex items-center gap-2 rounded-full">
              <GraduationCap className="h-4 w-4" />
              Filter by Level
            </Button>
          </div>
        </div>

        {loading ? (
          <div className="flex h-64 items-center justify-center text-muted-foreground">Loading your library...</div>
        ) : filteredCards.length === 0 ? (
          <div className="text-center py-20 space-y-4">
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
              <BookOpen className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium">No cards found</h3>
            <p className="text-muted-foreground">Start talking with the tutor to generate review cards!</p>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {filteredCards.map((card) => (
              <Card key={card.id} className="group hover:shadow-md transition-all border-t-2 border-t-transparent hover:border-t-primary">
                <CardContent className="p-6 space-y-4">
                  <div className="flex items-start justify-between">
                    <Badge variant="secondary" className="uppercase tracking-wider text-[10px]">
                      {card.type}
                    </Badge>
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
            ))}
          </div>
        )}
      </div>
    </DashboardLayout>
  )
}
