// Pure helpers + row shapes for the Progress page.
//
// Everything here is side-effect free: the page fetches rows from Supabase and
// calls into these functions, so the math stays reviewable apart from the UI.
//
// Rating ints are FSRS's enum: 1=Again 2=Hard 3=Good 4=Easy. Voca only ever
// emits Again/Good/Easy, and a "positive recall" is anything the learner did
// not miss (rating >= 3).

import {
  addDays,
  addMonths,
  differenceInCalendarDays,
  format,
  startOfDay,
  startOfMonth,
  subDays,
  subMonths,
} from "date-fns"

// --- Row shapes as stored in Supabase ---

/** The JSON in `cards.fsrs_data` (fsrs v6 `Card.to_dict()`; no review counters). */
export type FsrsState = {
  card_id: number
  state: number | null
  step: number | null
  stability: number | null
  difficulty: number | null
  due: string
  last_review: string | null
}

export type SessionRow = {
  start_time: string | null
  status: string
  recap: { user_word_count?: number } | null
}

export type CardRow = {
  // JSONB value as it arrives from PostgREST: double-encoded JSON string when
  // written by the backend (`new_card_state()`/review updates) or a parsed
  // object. Always pass through `parseFsrsData` before reading fields.
  fsrs_data: unknown
  next_review: string | null
}

export type ReviewRow = {
  rating: number
  reviewed_at: string
}

/** FSRS rating at/above which a review counts as a positive recall. */
export const POSITIVE_RATING_MIN = 3

/** Read `cards.fsrs_data` regardless of which writer produced it. */
export function parseFsrsData(raw: unknown): FsrsState | null {
  if (!raw) return null
  if (typeof raw === "string") {
    try {
      return JSON.parse(raw) as FsrsState
    } catch {
      return null
    }
  }
  return typeof raw === "object" ? (raw as FsrsState) : null
}

export type Range = "week" | "month" | "year" | "all"

export const RANGES: { value: Range; label: string }[] = [
  { value: "week", label: "Week" },
  { value: "month", label: "Month" },
  { value: "year", label: "Year" },
  { value: "all", label: "All" },
]

// --- Time windows and buckets -------------------------------------------------
//
// Week/Month are daily buckets (the last 7/30 days, today included); Year is
// the last 12 calendar months; "All" is monthly since the user's first data.

const DAY_KEY = "yyyy-MM-dd"
const MONTH_KEY = "yyyy-MM"

/** Chart buckets for `range`, chronological ascending. */
export function buildBuckets(range: Range, now: Date, earliest: Date | null): Bucket[] {
  const buckets: Bucket[] = []
  if (isDaily(range)) {
    const first = range === "week" ? startOfDay(subDays(now, 6)) : startOfDay(subDays(now, 29))
    for (let day = first; day <= now; day = addDays(day, 1)) {
      buckets.push({ key: format(day, DAY_KEY), label: format(day, "MMM d") })
    }
    return buckets
  }
  const first =
    range === "year"
      ? startOfMonth(subMonths(now, 11))
      : startOfMonth(earliest ? startOfDay(earliest) : now)
  for (let month = first; month <= now; month = addMonths(month, 1)) {
    buckets.push({ key: format(month, MONTH_KEY), label: format(month, "MMM yy") })
  }
  return buckets
}

export function isDaily(range: Range): boolean {
  return range === "week" || range === "month"
}

export function bucketKey(date: Date, range: Range): string {
  return format(date, isDaily(range) ? DAY_KEY : MONTH_KEY)
}

export type Bucket = { key: string; label: string }

/** The first instant included in the range (for filtering rows by timestamp). */
export function windowStart(range: Range, now: Date, earliest: Date | null): Date {
  const first = buildBuckets(range, now, earliest)[0]
  if (!first) return now
  const [year, month, day] = first.key.split("-").map(Number)
  return day == null ? new Date(year, month - 1, 1) : new Date(year, month - 1, day)
}

export function windowDays(range: Range, now: Date, earliest: Date | null): number {
  return Math.max(1, differenceInCalendarDays(now, windowStart(range, now, earliest)) + 1)
}

/** Count rows into the buckets; timestamps outside the window are ignored. */
export function countByBucket(buckets: Bucket[], range: Range, dates: Date[]): number[] {
  const counts = new Map<string, number>()
  for (const date of dates) {
    const key = bucketKey(date, range)
    counts.set(key, (counts.get(key) ?? 0) + 1)
  }
  return buckets.map((bucket) => counts.get(bucket.key) ?? 0)
}

/** Sum `value` per bucket; timestamps outside the window are ignored. */
export function sumByBucket(
  buckets: Bucket[],
  range: Range,
  items: { at: Date; value: number }[],
): number[] {
  const sums = new Map<string, number>()
  for (const item of items) {
    const key = bucketKey(item.at, range)
    sums.set(key, (sums.get(key) ?? 0) + item.value)
  }
  return buckets.map((bucket) => sums.get(bucket.key) ?? 0)
}

/** Reviews split into positive recalls vs misses, per bucket. */
export function splitReviewsByBucket(
  buckets: Bucket[],
  range: Range,
  reviews: ReviewRow[],
): { positive: number[]; missed: number[] } {
  const positiveCounts = new Map<string, number>()
  const missedCounts = new Map<string, number>()
  for (const review of reviews) {
    const key = bucketKey(new Date(review.reviewed_at), range)
    const target = review.rating >= POSITIVE_RATING_MIN ? positiveCounts : missedCounts
    target.set(key, (target.get(key) ?? 0) + 1)
  }
  return {
    positive: buckets.map((bucket) => positiveCounts.get(bucket.key) ?? 0),
    missed: buckets.map((bucket) => missedCounts.get(bucket.key) ?? 0),
  }
}

// --- Speaking activity ---------------------------------------------------------

export type SpeakingStats = {
  sessions: number
  activeDays: number
  words: number
  sessionsPerDay: number
  wordsPerDay: number
}

/**
 * Sessions/words/active-days for the already-range-filtered sessions, averaged
 * over `days` (the window's length, today included).
 */
export function speakingStats(sessions: SessionRow[], days: number): SpeakingStats {
  const activeDays = new Set<string>()
  let words = 0
  for (const session of sessions) {
    if (session.start_time) {
      activeDays.add(format(startOfDay(new Date(session.start_time)), DAY_KEY))
    }
    words += session.recap?.user_word_count ?? 0
  }
  const window = Math.max(1, days)
  return {
    sessions: sessions.length,
    activeDays: activeDays.size,
    words,
    sessionsPerDay: sessions.length / window,
    wordsPerDay: words / window,
  }
}

// --- Single-card labels (shared with the card library page) ------------------

export type CardStateLabel = 'New' | 'Learning' | 'Review'

/** Display state for one card; "new" = never studied (fsrs v6 has no New state). */
export function cardStateLabel(card: Pick<CardRow, 'fsrs_data'>): CardStateLabel {
  const fsrs = parseFsrsData(card.fsrs_data)
  if (!fsrs?.last_review) return 'New'
  return fsrs.state === 2 ? 'Review' : 'Learning' // Learning(1)/Relearning(3)
}

/** "Due now"/"Due <date>" copy for one card; null when it has no due date. */
export function dueLabel(
  card: Pick<CardRow, 'next_review'>,
  now: Date = new Date(),
): string | null {
  if (!card.next_review) return null
  const due = new Date(card.next_review)
  const daysOut = differenceInCalendarDays(due, now)
  if (daysOut <= 0) return 'Due now'
  if (daysOut === 1) return 'Due tomorrow'
  return `Due ${format(due, 'MMM d')}`
}

// --- Review-card snapshot --------------------------------------------------------

export type CardStats = {
  total: number
  dueNow: number
  new: number
  learning: number
  review: number
  lifetimeReviews: number
  lifetimePositive: number
  recallRate: number
}

/**
 * Current-state snapshot. FSRS v6 has no distinct "new" state value: a
 * never-studied card serializes as `state: 1` with `last_review: null`, so
 * "new" means no `last_review` at all. Cards are due when they were never
 * studied or their `next_review` has passed.
 */
export function cardStats(cards: CardRow[], reviews: ReviewRow[], now: Date): CardStats {
  let dueNow = 0
  let newCount = 0
  let learning = 0
  let review = 0
  for (const card of cards) {
    const fsrs = parseFsrsData(card.fsrs_data)
    const state = fsrs?.state
    const neverStudied = !fsrs?.last_review
    if (state === 2) review += 1
    else if (neverStudied) newCount += 1
    else if (state === 1 || state === 3) learning += 1
    else newCount += 1 // no fsrs_data at all: treat like a fresh card

    if (neverStudied || (card.next_review && new Date(card.next_review) <= now)) {
      dueNow += 1
    }
  }
  const lifetimePositive = reviews.filter((review) => review.rating >= POSITIVE_RATING_MIN).length
  const lifetimeReviews = reviews.length
  return {
    total: cards.length,
    dueNow,
    new: newCount,
    learning,
    review,
    lifetimeReviews,
    lifetimePositive,
    recallRate: lifetimeReviews === 0 ? 0 : lifetimePositive / lifetimeReviews,
  }
}
