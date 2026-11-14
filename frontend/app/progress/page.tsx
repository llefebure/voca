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
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Tabs, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { Activity, GraduationCap, Info, Mic, TrendingUp } from 'lucide-react'
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
  Tooltip as ChartTooltip,
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
  tip,
}: {
  label: string
  value: string | number
  caption?: string
  danger?: boolean
  tip?: string
}) {
  return (
    <div className="rounded-xl bg-muted/50 p-4 border text-center">
      <p className="flex items-center justify-center gap-1 text-xs text-muted-foreground font-medium uppercase tracking-wider">
        {label}
        {tip && (
          <Tooltip>
            <TooltipTrigger
              render={
                <span
                  tabIndex={0}
                  aria-label={`About ${label}`}
                  className="inline-flex size-4 cursor-help items-center justify-center rounded text-muted-foreground/70 transition-colors hover:text-foreground focus-visible:outline-1 focus-visible:outline-ring"
                >
                  <Info className="size-3.5" />
                </span>
              }
            />
            <TooltipContent className="max-w-56 text-left leading-relaxed">{tip}</TooltipContent>
          </Tooltip>
        )}
      </p>
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
              tip="How many conversations you practiced in this range (every started session counts, ended or not)."
            />
            <StatTile
              label="Active days"
              value={fmt(speaking.activeDays)}
              caption={`of ${days} days`}
              tip="Days in this range with at least one practice session."
            />
            <StatTile
              label="Words spoken"
              value={fmt(speaking.words)}
              caption={`${speaking.wordsPerDay.toFixed(1)} / day`}
              tip="Everything you said across this range's sessions — read from each session's recap when it ends."
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
                <ChartTooltip cursor={{ fill: 'var(--muted)', fillOpacity: 0.5 }} contentStyle={TOOLTIP_STYLE} />
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
            <StatTile
              label="Card reviews"
              value={fmt(rangeReviews.length)}
              tip="Graded reviews of study cards logged during this range's ended sessions."
            />
            <StatTile
              label="Positive recalls"
              value={fmt(rangeReviewPositive)}
              tip="Reviews where you produced or clearly recognized the card (graded Good or Easy)."
            />
            <StatTile
              label="Recall rate"
              value={`${rangeRecallRate}%`}
              tip="Positive recalls out of all card reviews in this range."
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
                <ChartTooltip cursor={{ fill: 'var(--muted)', fillOpacity: 0.5 }} contentStyle={TOOLTIP_STYLE} />
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
            <StatTile
              label="Total cards"
              value={fmt(snapshot.total)}
              tip="Every review card built from your sessions for this language."
            />
            <StatTile
              label="Due now"
              value={fmt(snapshot.dueNow)}
              danger={snapshot.dueNow > 0}
              tip="Cards past their due date — plus new cards (they're born due). This is the pool the tutor picks review targets from."
            />
            <StatTile
              label="New"
              value={fmt(snapshot.new)}
              tip="Created for you but never quizzed yet — they go into study immediately."
            />
            <StatTile
              label="Learning"
              value={fmt(snapshot.learning)}
              caption="relearning included"
              tip="Cards on short, minute-scale schedules — first learning steps, or a previously known card you forgot and are now relearning."
            />
            <StatTile
              label="In review"
              value={fmt(snapshot.review)}
              tip="Cards that graduated to long-term scheduling (days to months). They only drop back to learning if you miss one."
            />
            <StatTile
              label="Recalls (all time)"
              value={fmt(snapshot.lifetimePositive)}
              caption={`of ${fmt(snapshot.lifetimeReviews)} reviews`}
              tip="All-time logged reviews where you recalled the card (Good or Easy). Misses are logged too, just not counted here."
            />
            <StatTile
              label="Recall rate"
              value={`${Math.round(snapshot.recallRate * 100)}%`}
              caption="all time"
              tip="All-time positive recalls out of every logged review for this language."
            />
          </div>
        </CardContent>
      </Card>
    </>
  )
}
