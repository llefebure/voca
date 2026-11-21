import { describe, expect, it } from 'vitest'
import {
  buildBuckets,
  cardStateLabel,
  cardStats,
  countByBucket,
  dueLabel,
  isDaily,
  parseFsrsData,
  splitReviewsByBucket,
  speakingStats,
  sumByBucket,
  windowDays,
  type CardRow,
  type ReviewRow,
  type SessionRow,
} from '@/lib/stats'

const NOW = new Date('2026-03-15T12:00:00')

describe('parseFsrsData', () => {
  it('parses double-encoded JSON strings, passes objects, nulls garbage', () => {
    expect(parseFsrsData('{"state":2,"due":"2026-01-01"}')).toEqual({
      state: 2,
      due: '2026-01-01',
    })
    const obj = { state: 3, due: '2026-01-01' }
    expect(parseFsrsData(obj)).toBe(obj)
    expect(parseFsrsData('not json')).toBeNull()
    expect(parseFsrsData(null)).toBeNull()
    expect(parseFsrsData('')).toBeNull()
    expect(parseFsrsData(42)).toBeNull()
  })
})

describe('buildBuckets / windows', () => {
  it('week = 7 daily buckets ending today', () => {
    const buckets = buildBuckets('week', NOW, null)
    expect(isDaily('week')).toBe(true)
    expect(buckets).toHaveLength(7)
    expect(buckets.at(-1)?.key).toBe('2026-03-15')
    expect(buckets[0]?.key).toBe('2026-03-09')
  })

  it('month = 30 daily buckets', () => {
    expect(buildBuckets('month', NOW, null)).toHaveLength(30)
  })

  it('year = last 12 calendar months', () => {
    const buckets = buildBuckets('year', NOW, null)
    expect(isDaily('year')).toBe(false)
    expect(buckets).toHaveLength(12)
    expect(buckets[0]?.key).toBe('2025-04')
    expect(buckets.at(-1)?.key).toBe('2026-03')
  })

  it('all spans monthly from the earliest data point', () => {
    const buckets = buildBuckets('all', NOW, new Date('2025-11-20'))
    expect(buckets.map((b) => b.key)).toEqual([
      '2025-11',
      '2025-12',
      '2026-01',
      '2026-02',
      '2026-03',
    ])
  })

  it('windowDays counts today (week = 7)', () => {
    expect(windowDays('week', NOW, null)).toBe(7)
    expect(windowDays('month', NOW, null)).toBe(30)
  })
})

describe('countByBucket / sumByBucket', () => {
  const buckets = buildBuckets('week', NOW, null) // 2026-03-09 .. 2026-03-15

  it('counts dates into daily buckets, ignoring dates outside the window', () => {
    const dates = [
      new Date('2026-03-10T08:00'),
      new Date('2026-03-10T20:00'),
      new Date('2026-03-15T10:00'),
      new Date('2026-02-01T10:00'), // outside
    ]
    const counts = countByBucket(buckets, 'week', dates)
    const byDay = new Map(buckets.map((b, i) => [b.key, counts[i]]))
    expect(byDay.get('2026-03-10')).toBe(2)
    expect(byDay.get('2026-03-15')).toBe(1)
    expect(counts.reduce((a, b) => a + b, 0)).toBe(3)
  })

  it('sums values per bucket', () => {
    const sums = sumByBucket(buckets, 'week', [
      { at: new Date('2026-03-10T08:00'), value: 3 },
      { at: new Date('2026-03-10T09:00'), value: 4 },
      { at: new Date('2026-03-15T09:00'), value: 5 },
      { at: new Date('2026-01-01T09:00'), value: 100 }, // outside
    ])
    expect(sums).toHaveLength(7)
    expect(sums[1]).toBe(7) // 2026-03-10
    expect(sums[6]).toBe(5) // 2026-03-15
  })
})

describe('splitReviewsByBucket', () => {
  const buckets = buildBuckets('week', NOW, null)

  it('splits positive recalls (rating >= 3) from misses', () => {
    const reviews: ReviewRow[] = [
      { rating: 1, reviewed_at: '2026-03-10T10:00' },
      { rating: 2, reviewed_at: '2026-03-10T11:00' },
      { rating: 3, reviewed_at: '2026-03-10T12:00' },
      { rating: 4, reviewed_at: '2026-03-15T08:00' },
      { rating: 3, reviewed_at: '2026-02-01T08:00' }, // outside window
    ]
    const { positive, missed } = splitReviewsByBucket(buckets, 'week', reviews)
    expect(positive[1]).toBe(1) // 2026-03-10
    expect(missed[1]).toBe(2) // 2026-03-10
    expect(positive[6]).toBe(1) // 2026-03-15
    expect(positive.reduce((a, b) => a + b, 0)).toBe(2)
    expect(missed.reduce((a, b) => a + b, 0)).toBe(2)
  })
})

describe('speakingStats', () => {
  it('counts sessions, active days, words and daily averages', () => {
    const sessions: SessionRow[] = [
      { start_time: '2026-03-10T10:00', status: 'completed', recap: { user_word_count: 30 } },
      { start_time: '2026-03-10T18:00', status: 'completed', recap: { user_word_count: 20 } }, // same day
      { start_time: null, status: 'completed', recap: { user_word_count: 10 } }, // no start time
      { start_time: '2026-03-12T10:00', status: 'active', recap: null },
    ]
    const stats = speakingStats(sessions, 7)
    expect(stats.sessions).toBe(4)
    expect(stats.activeDays).toBe(2)
    expect(stats.words).toBe(60)
    expect(stats.sessionsPerDay).toBeCloseTo(4 / 7)
    expect(stats.wordsPerDay).toBeCloseTo(60 / 7)
  })
})

describe('cardStateLabel / dueLabel', () => {
  it('labels never-studied cards New (v6 has no New state value)', () => {
    expect(cardStateLabel({ fsrs_data: { state: 1, last_review: null } })).toBe('New')
    expect(cardStateLabel({ fsrs_data: null })).toBe('New')
  })

  it('labels state 2 Review, states 1/3 Learning', () => {
    expect(cardStateLabel({ fsrs_data: { state: 2, last_review: '2026-01-01' } })).toBe('Review')
    expect(cardStateLabel({ fsrs_data: { state: 1, last_review: '2026-01-01' } })).toBe('Learning')
    expect(cardStateLabel({ fsrs_data: { state: 3, last_review: '2026-01-01' } })).toBe('Learning')
  })

  it('dueLabel: due today/past → "Due now", 1 day → tomorrow, then date', () => {
    const now = new Date('2026-03-15T12:00')
    expect(dueLabel({ next_review: '2026-03-15T18:00' }, now)).toBe('Due now')
    expect(dueLabel({ next_review: '2026-03-14T08:00' }, now)).toBe('Due now')
    expect(dueLabel({ next_review: '2026-03-16T08:00' }, now)).toBe('Due tomorrow')
    expect(dueLabel({ next_review: '2026-03-20T08:00' }, now)).toBe('Due Mar 20')
    expect(dueLabel({ next_review: null }, now)).toBeNull()
    expect(dueLabel({ next_review: '2026-03-20' }, null)).toBeNull()
  })
})

describe('cardStats', () => {
  it('buckets by state, counts due cards and lifetime recall rate', () => {
    const now = new Date('2026-03-15T12:00')
    const cards: CardRow[] = [
      { fsrs_data: null, next_review: null }, // new, due now
      {
        // Never-studied cards are always due, even with a future next_review.
        fsrs_data: JSON.stringify({ state: 1, last_review: null, due: '2026-03-20' }),
        next_review: '2026-03-20T10:00',
      }, // new, due now
      {
        fsrs_data: JSON.stringify({ state: 1, last_review: '2026-03-13' }),
        next_review: '2026-03-14T10:00',
      }, // learning, due (next_review < now)
      {
        fsrs_data: JSON.stringify({ state: 2, last_review: '2026-03-13' }),
        next_review: '2026-03-16T10:00',
      }, // review, not due
      {
        fsrs_data: JSON.stringify({ state: 3, last_review: '2026-03-13' }),
        next_review: '2026-03-17T10:00',
      }, // learning, not due
    ]
    const reviews: ReviewRow[] = [
      { rating: 3, reviewed_at: '2026-03-13' },
      { rating: 4, reviewed_at: '2026-03-13' },
      { rating: 1, reviewed_at: '2026-03-14' },
      { rating: 2, reviewed_at: '2026-03-14' },
    ]
    const stats = cardStats(cards, reviews, now)
    expect(stats.total).toBe(5)
    expect(stats.new).toBe(2)
    expect(stats.learning).toBe(2)
    expect(stats.review).toBe(1)
    expect(stats.dueNow).toBe(3)
    expect(stats.lifetimeReviews).toBe(4)
    expect(stats.lifetimePositive).toBe(2)
    expect(stats.recallRate).toBe(0.5)
  })

  it('empty cards and reviews: zeroed snapshot with recallRate 0', () => {
    const stats = cardStats([], [], new Date())
    expect(stats).toMatchObject({
      total: 0,
      dueNow: 0,
      new: 0,
      learning: 0,
      review: 0,
      lifetimeReviews: 0,
      lifetimePositive: 0,
      recallRate: 0,
    })
  })
})
