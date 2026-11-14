'use client'

// /progress — learning metrics for the active language: speaking activity
// (sessions/active days/words), review activity (logged positive recalls vs
// misses), and the current review-card snapshot. All math lives in lib/stats;
// this page fetches (Supabase anon + RLS, like the library page) and renders.
//
// The clock used for ranges and buckets is created in the fetch effect and
// handed down as a prop: reading `new Date()` during render is an unstable
// value that a Next 16 prerender pass rejects (blocking-prerender-current-time).

import { useEffect, useMemo, useState } from 'react'
import { useRouter } from 'next/navigation'
import { supabase } from '@/lib/supabase'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Activity, GraduationCap, Mic, TrendingUp } from 'lucide-react'
import { DashboardLayout } from '@/components/dashboard-layout'
import { useLanguage } from '@/components/language-context'
import {
  POSITIVE_RATING_MIN,
  RANGES,
  type CardRow,
  type Range,
  type ReviewRow,
  type SessionRow,
  cardStats,
  buildBuckets,
  countByBucket,
  splitReviewsByBucket,
  speakingStats,
  sumByBucket,
  windowDays,
  windowStart,
} from '@/lib/stats'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

// Recharts styling resolved from the app's CSS tokens (SVG fills accept vars).
const AXIS_TICK = { fontSize: 11, fill: 'var(--muted-foreground)' }
const TOOLTIP_STYLE = {
  background: 'var(--popover)',
  border: '1px solid var(--border)',
  borderRadius: 8,
  fontSize: 12,
  color: 'var(--foreground)',
}

function StatTile({
  label,
  value,
  caption,
  danger,
}: {
  label: string
  value: string | number
  caption?: string
  danger?: boolean
}) {
  return (
    <div className="rounded-xl bg-muted/50 p-4 border text-center">
      <p className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{label}</p>
      <p className={`text-3xl font-bold ${danger ? 'text-destructive' : ''}`}>{value}</p>
      {caption && <p className="text-xs text-muted-foreground mt-1">{caption}</p>}
    </div>
  )
}

export default function ProgressPage() {
  const [sessions, setSessions] = useState<SessionRow[]>([])
  const [cards, setCards] = useState<CardRow[]>([])
  const [reviews, setReviews] = useState<ReviewRow[]>([])
  const [loading, setLoading] = useState(true)
  // Set to the moment of (re)load in the effect below, so no current-time
  // read happens during render (see the file-level note).
  const [now, setNow] = useState<Date | null>(null)
  const router = useRouter()
  // Progress is scoped to the active language, like the library and history.
  const { activeLanguage, loading: languageLoading } = useLanguage()

  useEffect(() => {
    if (languageLoading || !activeLanguage) return
    const fetchProgress = async () => {
      try {
        const { data: { user } } = await supabase.auth.getUser()
        if (!user) {
          router.push('/auth')
          return
        }

        // Pin "now" to the fetch moment: ranges/buckets must not drift while
        // the user toggles through ranges on loaded data.
        setNow(new Date())
        const [sessionsRes, cardsRes, reviewsRes] = await Promise.all([
          supabase
            .from('sessions')
            .select('start_time, status, recap')
            .eq('user_id', user.id)
            .eq('language', activeLanguage),
          supabase
            .from('cards')
            .select('fsrs_data, next_review')
            .eq('user_id', user.id)
            .eq('language', activeLanguage),
          supabase
            .from('card_reviews')
            .select('rating, reviewed_at')
            .eq('user_id', user.id)
            .eq('language', activeLanguage),
        ])
        if (sessionsRes.error || cardsRes.error || reviewsRes.error) {
          throw sessionsRes.error ?? cardsRes.error ?? reviewsRes.error
        }
        setSessions((sessionsRes.data ?? []) as unknown as SessionRow[])
        setCards((cardsRes.data ?? []) as unknown as CardRow[])
        setReviews((reviewsRes.data ?? []) as unknown as ReviewRow[])
      } catch (error) {
        console.error('Error fetching progress:', error)
      } finally {
        setLoading(false)
      }
    }
    fetchProgress()
  }, [router, activeLanguage, languageLoading])

  const loadingPage = loading || languageLoading || now === null
  const hasAnyData =
    sessions.length > 0 || cards.length > 0 || reviews.length > 0

  return (
    <DashboardLayout title="Progress">
      <div className="mx-auto max-w-5xl space-y-8 p-4 md:p-8">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Title is in DashboardLayout */}
          </div>
          <Button variant="outline" onClick={() => router.push('/')}>
            Start Practicing
          </Button>
        </div>

        {loadingPage || !now ? (
          <div className="flex h-64 items-center justify-center text-muted-foreground">
            Loading your progress...
          </div>
        ) : !hasAnyData ? (
          <div className="text-center py-20 space-y-4">
            <div className="mx-auto w-16 h-16 bg-muted rounded-full flex items-center justify-center">
              <Activity className="h-8 w-8 text-muted-foreground" />
            </div>
            <h3 className="text-lg font-medium">No progress yet</h3>
            <p className="text-muted-foreground">
              Practice with the tutor and finish a session — your activity will show up here.
            </p>
          </div>
        ) : (
          <ProgressContent sessions={sessions} cards={cards} reviews={reviews} now={now} />
        )}
      </div>
    </DashboardLayout>
  )
}

function ProgressContent({
  sessions,
  cards,
  reviews,
  now,
}: {
  sessions: SessionRow[]
  cards: CardRow[]
  reviews: ReviewRow[]
  now: Date
}) {
  const [range, setRange] = useState<Range>('week')

  const earliest = useMemo(() => {
    const times = [
      ...sessions.map((s) => (s.start_time ? new Date(s.start_time).getTime() : null)),
      ...reviews.map((r) => (r.reviewed_at ? new Date(r.reviewed_at).getTime() : null)),
    ].filter((time): time is number => time !== null)
    return times.length === 0 ? null : new Date(Math.min(...times))
  }, [sessions, reviews])

  const start = useMemo(() => windowStart(range, now, earliest), [range, now, earliest])
  const buckets = useMemo(() => buildBuckets(range, now, earliest), [range, now, earliest])
  const rangeSessions = useMemo(
    () => sessions.filter((s) => s.start_time && new Date(s.start_time) >= start),
    [sessions, start],
  )
  const rangeReviews = useMemo(
    () => reviews.filter((r) => new Date(r.reviewed_at) >= start),
    [reviews, start],
  )

  const days = windowDays(range, now, earliest)
  const speaking = useMemo(() => speakingStats(rangeSessions, days), [rangeSessions, days])
  const chartData = useMemo(() => {
    const words = sumByBucket(
      buckets,
      range,
      rangeSessions.map((s) => ({
        at: new Date(s.start_time as string),
        value: s.recap?.user_word_count ?? 0,
      })),
    )
    const reviewCounts = countByBucket(
      buckets,
      range,
      rangeReviews.map((r) => new Date(r.reviewed_at)),
    )
    const split = splitReviewsByBucket(buckets, range, rangeReviews)
    return buckets.map((bucket, i) => ({
      label: bucket.label,
      words: words[i],
      reviews: reviewCounts[i],
      positive: split.positive[i],
      missed: split.missed[i],
    }))
  }, [buckets, range, rangeSessions, rangeReviews])
  const snapshot = useMemo(() => cardStats(cards, reviews, now), [cards, reviews, now])

  const rangeReviewPositive = rangeReviews.filter((r) => r.rating >= POSITIVE_RATING_MIN).length
  const rangeRecallRate =
    rangeReviews.length === 0 ? 0 : Math.round((rangeReviewPositive / rangeReviews.length) * 100)

  const fmt = (value: number) => Math.round(value).toLocaleString()

  return (
    <>
      {/* The toggle scopes both activity sections; the snapshot stays fixed. */}
      <div className="flex items-center justify-between gap-4">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Activity range
        </h2>
        <Tabs value={range} onValueChange={(value) => setRange(value as Range)}>
          <TabsList>
            {RANGES.map((option) => (
              <TabsTrigger key={option.value} value={option.value}>
                {option.label}
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>
      </div>

      <Card className="border-t-4 border-t-primary">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <Mic className="h-5 w-5 text-muted-foreground" />
            Speaking activity
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile
              label="Sessions"
              value={fmt(speaking.sessions)}
              caption={`${speaking.sessionsPerDay.toFixed(1)} / day`}
            />
            <StatTile
              label="Active days"
              value={fmt(speaking.activeDays)}
              caption={`of ${days} days`}
            />
            <StatTile
              label="Words spoken"
              value={fmt(speaking.words)}
              caption={`${speaking.wordsPerDay.toFixed(1)} / day`}
            />
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={18}
                />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip cursor={{ fill: 'var(--muted)', fillOpacity: 0.5 }} contentStyle={TOOLTIP_STYLE} />
                <Bar
                  dataKey="words"
                  name="Words spoken"
                  fill="var(--chart-1)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card className="border-t-4 border-t-primary/30">
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <GraduationCap className="h-5 w-5 text-muted-foreground" />
            Review activity
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-6">
          <div className="grid gap-4 sm:grid-cols-3">
            <StatTile label="Card reviews" value={fmt(rangeReviews.length)} />
            <StatTile
              label="Positive recalls"
              value={fmt(rangeReviewPositive)}
            />
            <StatTile label="Recall rate" value={`${rangeRecallRate}%`} />
          </div>
          <div className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="var(--border)" />
                <XAxis
                  dataKey="label"
                  tick={AXIS_TICK}
                  tickLine={false}
                  axisLine={false}
                  minTickGap={18}
                />
                <YAxis tick={AXIS_TICK} tickLine={false} axisLine={false} allowDecimals={false} />
                <Tooltip cursor={{ fill: 'var(--muted)', fillOpacity: 0.5 }} contentStyle={TOOLTIP_STYLE} />
                <Legend iconType="circle" wrapperStyle={{ fontSize: 12 }} />
                <Bar
                  dataKey="positive"
                  name="Positive recall"
                  stackId="reviews"
                  fill="var(--success)"
                  radius={[0, 0, 0, 0]}
                />
                <Bar
                  dataKey="missed"
                  name="Missed"
                  stackId="reviews"
                  fill="var(--destructive)"
                  radius={[4, 4, 0, 0]}
                />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg flex items-center gap-2">
            <TrendingUp className="h-5 w-5 text-muted-foreground" />
            Cards
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Total cards" value={fmt(snapshot.total)} />
            <StatTile
              label="Due now"
              value={fmt(snapshot.dueNow)}
              danger={snapshot.dueNow > 0}
            />
            <StatTile label="New" value={fmt(snapshot.new)} />
            <StatTile
              label="Learning"
              value={fmt(snapshot.learning)}
              caption="relearning included"
            />
            <StatTile label="In review" value={fmt(snapshot.review)} />
            <StatTile
              label="Recalls (all time)"
              value={fmt(snapshot.lifetimePositive)}
              caption={`of ${fmt(snapshot.lifetimeReviews)} reviews`}
            />
            <StatTile
              label="Recall rate"
              value={`${Math.round(snapshot.recallRate * 100)}%`}
              caption="all time"
            />
          </div>
        </CardContent>
      </Card>
    </>
  )
}
