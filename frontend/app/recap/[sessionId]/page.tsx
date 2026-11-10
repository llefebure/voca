'use client'

import { useState, useEffect, use } from 'react'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { useRouter } from 'next/navigation'
import { CheckCircle, XCircle, BookOpen, ArrowRight, TrendingUp, Target } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'

type RecapData = {
  time_spoken?: string
  lesson_completed?: boolean
  positives?: string[]
  key_corrections?: string[]
  next_time_preview?: string
}

type CardRow = {
  id: string
  type: string
  front: string
  back: string
  source_sentence?: string | null
}

export default function RecapPage({ params }: { params: Promise<{ sessionId: string }> }) {
  const { sessionId } = use(params)
  const [recap, setRecap] = useState<RecapData | null>(null)
  const [cards, setCards] = useState<CardRow[]>([])
  const [loading, setLoading] = useState(true)
  const router = useRouter()

  useEffect(() => {
    const fetchRecap = async () => {
      try {
        const { data: session } = await supabase
          .from('sessions')
          .select('recap, user_id')
          .eq('id', sessionId)
          .single()

        if (!session) {
          router.push('/')
          return
        }

        const { data: cardsData } = await supabase
          .from('cards')
          .select('*')
          .eq('user_id', session.user_id)
          .order('created_at', { ascending: false })
          .limit(10)

        setRecap((session.recap as RecapData) ?? null)
        setCards(cardsData || [])
      } catch (error) {
        console.error('Error fetching recap:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchRecap()
  }, [sessionId, router])

  if (loading) return (
    <DashboardLayout title="Loading Recap">
      <div className="flex h-full items-center justify-center text-muted-foreground">Loading your session analysis...</div>
    </DashboardLayout>
  )
  if (!recap) return (
    <DashboardLayout title="No Recap">
      <div className="flex h-full items-center justify-center text-muted-foreground">No recap found for this session.</div>
    </DashboardLayout>
  )

  return (
    <DashboardLayout title="Session Recap">
      <div className="mx-auto max-w-3xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            {/* Title is in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Start New Session
          </Button>
        </div>

        <Card className="border-t-4 border-t-primary">
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              <TrendingUp className="h-5 w-5 text-primary" />
              Performance Overview
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="grid grid-cols-2 gap-4">
              <div className="rounded-xl bg-muted/50 p-4 text-center border">
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Time Spoken</p>
                <p className="text-2xl font-bold">{recap.time_spoken || 'N/A'}</p>
              </div>
              <div className="rounded-xl bg-muted/50 p-4 text-center border">
                <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">Lesson Status</p>
                <p className="text-2xl font-bold">{recap.lesson_completed ? 'Completed' : 'In Progress'}</p>
              </div>
            </div>

            <div className="grid gap-6">
              <div className="space-y-3">
                <h3 className="font-semibold flex items-center gap-2 text-sm uppercase tracking-wider text-muted-foreground">
                  <CheckCircle className="h-4 w-4 text-green-500" />
                  Wins & Progress
                </h3>
                <ul className="space-y-2">
                  {recap.positives?.map((positive, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm bg-green-50 dark:bg-green-900/10 p-2 rounded-lg border border-green-100 dark:border-green-900/30">
                      <span className="text-green-500 mt-1">•</span>
                      {positive}
                    </li>
                  ))}
                </ul>
              </div>

              <div className="space-y-3">
                <h3 className="font-semibold flex items-center gap-2 text-sm uppercase tracking-wider text-muted-foreground">
                  <XCircle className="h-4 w-4 text-destructive" />
                  Areas for Improvement
                </h3>
                <ul className="space-y-2">
                  {recap.key_corrections?.map((correction, i) => (
                    <li key={i} className="flex items-start gap-2 text-sm bg-destructive/5 p-2 rounded-lg border border-destructive/10">
                      <span className="text-destructive mt-1">•</span>
                      {correction}
                    </li>
                  ))}
                </ul>
              </div>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-xl flex items-center gap-2">
              <BookOpen className="h-5 w-5 text-primary" />
              Review Material
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {cards.length === 0 ? (
              <p className="text-muted-foreground italic text-center py-4">No new review cards this session.</p>
            ) : (
              <div className="grid gap-3">
                {cards.map((card) => (
                  <div key={card.id} className="flex items-center justify-between rounded-xl border p-4 bg-card shadow-sm hover:shadow-md transition-shadow">
                    <div className="space-y-1">
                      <p className="text-sm font-semibold">{card.front}</p>
                      <p className="text-xs text-muted-foreground">{card.back}</p>
                    </div>
                    <Badge variant="secondary" className="shrink-0">
                      {card.type}
                    </Badge>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <div className="text-center space-y-6 py-8">
          <div className="bg-primary/5 rounded-2xl p-6 border border-primary/10 max-w-md mx-auto space-y-3">
            <div className="flex items-center justify-center gap-2 text-primary font-semibold text-sm uppercase tracking-wider">
              <Target className="h-4 w-4" />
              Next Focus
            </div>
            <p className="text-lg font-medium italic">
              &quot;{recap.next_time_preview}&quot;
            </p>
          </div>
          <Button size="lg" className="w-full md:w-auto px-12 rounded-full transition-all hover:scale-105" onClick={() => router.push('/')}>
            Keep Practicing <ArrowRight className="ml-2 h-4 w-4" />
          </Button>
        </div>
      </div>
    </DashboardLayout>
  )
}
