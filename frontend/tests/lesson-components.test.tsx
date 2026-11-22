/** Lesson UI component tests, offline. */
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { LessonMaterial, LessonSummaryCard, ProposalCard } from '@/components/lesson/lesson-components'
import type { LessonInstance, MaterialBlock } from '@/lib/lesson-events'

function proposal(): LessonInstance {
  return {
    id: 'lesson-1',
    status: 'proposed',
    spec: {
      template: 'role_play',
      title: 'At the café',
      objectives: ['order politely', 'ask for the check'],
      minutes: 6,
    },
    material: [],
    target_cards: [],
    reason: 'you were just talking about coffee',
    intro_line: '¡Hola!',
    proposed_at: '2026-01-01T00:00:00+00:00',
  }
}

afterEach(cleanup)

describe('ProposalCard', () => {
  it('shows template, title, reason, objectives and duration', () => {
    render(<ProposalCard lesson={proposal()} onAccept={() => {}} onDecline={() => {}} />)
    expect(screen.getByText('At the café')).toBeVisible()
    expect(screen.getByText('you were just talking about coffee')).toBeVisible()
    expect(screen.getByText('order politely')).toBeVisible()
    expect(screen.getByText('Role Play')).toBeVisible()
    expect(screen.getByText('~6 min')).toBeVisible()
  })

  it('accept and decline buttons fire their callbacks', () => {
    const onAccept = vi.fn()
    const onDecline = vi.fn()
    render(<ProposalCard lesson={proposal()} onAccept={onAccept} onDecline={onDecline} />)
    fireEvent.click(screen.getByTestId('proposal-accept'))
    fireEvent.click(screen.getByTestId('proposal-decline'))
    expect(onAccept).toHaveBeenCalledTimes(1)
    expect(onDecline).toHaveBeenCalledTimes(1)
  })
})

describe('LessonMaterial', () => {
  it('renders each block type with its distinct treatment', () => {
    const material: MaterialBlock[] = [
      {
        type: 'scenario',
        setting: 'a café in Madrid',
        learner_role: 'customer',
        tutor_role: 'barista',
        goal: 'order and pay',
      },
      { type: 'text', title: 'Carta', markdown: '| Café | Precio |\n|---|---|\n| espresso | 1,20 € |' },
      { type: 'dialogue', turns: [{ speaker: 'tutor', text: '¡Buenas!' }, { speaker: 'learner', text: '' }] },
      { type: 'questions', items: ['¿Qué pide?'] },
      { type: 'word_bank', items: ['un cortado'] },
    ]
    render(<LessonMaterial lesson={{ ...proposal(), status: 'active', material }} />)
    expect(screen.getByTestId('lesson-material')).toBeVisible()
    expect(screen.getByText('a café in Madrid')).toBeVisible()
    expect(screen.getByText(/1,20 €/)).toBeVisible()
    expect(screen.getByTestId('dialogue-gap')).toBeVisible()
    expect(screen.getByText('¿Qué pide?')).toBeVisible()
    expect(screen.getByText('un cortado')).toBeVisible()
  })

  it('falls back gracefully for an unsupported block type', () => {
    const material = [{ type: 'mystery', x: 1 }] as unknown as MaterialBlock[]
    render(<LessonMaterial lesson={{ ...proposal(), status: 'active', material }} />)
    expect(screen.getByText('(Unsupported material block)')).toBeVisible()
  })
})

describe('LessonSummaryCard', () => {
  it('renders headline, bonus count, and per-card outcome marks', () => {
    render(
      <LessonSummaryCard
        lesson={{
          ...proposal(),
          status: 'completed',
          target_cards: [
            { id: 'card-1', front: 'quisiera', back: 'I would like' },
            { id: 'card-2', front: 'la cuenta', back: 'the check' },
          ],
          grades: [
            { card_id: 'card-1', outcome: 'strong_pass', bonus_use: true, evidence: 'e' },
            { card_id: 'card-2', outcome: 'recognition_pass', evidence: 'e' },
          ],
          summary: {
            headline: 'Ordered coffee confidently',
            positives: [],
            key_phrases: ['¿me trae la cuenta?'],
            bonus_uses: ['Quisiera un cortado.'],
          },
        }}
      />,
    )
    expect(screen.getByText('Ordered coffee confidently')).toBeVisible()
    expect(screen.getByTestId('lesson-summary')).toBeVisible()
    expect(screen.getByText(/1 bonus use/)).toBeVisible()
    expect(screen.getByText('quisiera')).toBeVisible()
    expect(screen.getByText('la cuenta')).toBeVisible()
    expect(screen.getByText('¿me trae la cuenta?')).toBeVisible()
  })
})
