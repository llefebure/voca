import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import {
  PanelBlocksList,
  PanelCanvas,
  PanelRecord,
} from '@/components/panel/panel-components'
import type { PanelBlock, PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'

afterEach(cleanup)

const MENU_MD = '**La Carta**\n\n| Plato | Precio |\n| :--- | :--- |\n| Tacos | 60 |'

function menuPanel(overrides: Partial<PanelInstance> = {}): PanelInstance {
  return {
    id: 'panel-abc123',
    title: 'Carta del día',
    blocks: [{ type: 'text', markdown: MENU_MD } as PanelBlock],
    ...overrides,
  }
}

describe('PanelBlocksList', () => {
  it('renders each block type with its distinct treatment', () => {
    render(
      <PanelBlocksList
        blocks={[
          { type: 'scenario', setting: 'A café', learner_role: 'customer', tutor_role: 'barista', goal: 'order' },
          { type: 'text', markdown: MENU_MD },
          { type: 'dialogue', turns: [{ speaker: 'tutor', text: '¡Buenas!' }, { speaker: 'learner', text: '' }] },
          { type: 'questions', items: ['¿Qué te apetece?'] },
          { type: 'tasks', items: [{ task: 'Pide la cuenta', hint: 'la cuenta' }] },
          { type: 'word_bank', items: ['un cortado'] },
        ]}
      />,
    )
    expect(screen.getByText('A café')).toBeVisible()
    expect(screen.getByTestId('dialogue-gap')).toBeVisible()
    expect(screen.getByText('¿Qué te apetece?')).toBeVisible()
    expect(screen.getByText('Pide la cuenta')).toBeVisible()
    expect(screen.getByText('un cortado')).toBeVisible()
    // The markdown table from the menu renders as a real <table>.
    expect(screen.getAllByRole('table').length).toBeGreaterThanOrEqual(1)
  })

  it('decodes stored literal escapes before rendering markdown', () => {
    render(
      <PanelBlocksList
        blocks={[{ type: 'text', markdown: '**Tacos**\\n\\n| Plato |\\n| :--- |' } as PanelBlock]}
      />,
    )
    // The literal sequence never reaches the DOM: the table renders.
    expect(screen.getByRole('table')).toBeVisible()
  })
})

describe('PanelCanvas', () => {
  it('shows the panel title and content, with a working close button', () => {
    const onClose = vi.fn()
    render(<PanelCanvas panel={menuPanel()} onClose={onClose} />)
    expect(screen.getByTestId('panel-canvas')).toBeVisible()
    expect(screen.getByText('Carta del día')).toBeVisible()
    fireEvent.click(screen.getByTestId('panel-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('omits the close button when the canvas is not dismissible', () => {
    render(<PanelCanvas panel={menuPanel()} />)
    expect(screen.queryByTestId('panel-close')).toBeNull()
  })
})

describe('PanelRecord', () => {
  it('collapses by default and expands to the content on click', () => {
    render(<PanelRecord panel={menuPanel()} />)
    expect(screen.queryByText('La Carta')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Carta del día/ }))
    expect(screen.getByText('La Carta')).toBeVisible()
  })
})

describe('cleanEscapedText', () => {
  it('decodes literal escape sequences in stored panel payloads', () => {
    const cleaned = cleanEscapedText({
      markdown: '**Hotel Sol y Luna**\\n\\n| Hora | Act |\\n| :--- | :--- |\\n| 8 | Desayuno |',
      nested: { text: 'línea 1\\nlínea 2' },
      untouched: 'sin secuencias',
      panel: menuPanel(),
    })
    expect(cleaned.markdown).toBe(
      '**Hotel Sol y Luna**\n\n| Hora | Act |\n| :--- | :--- |\n| 8 | Desayuno |',
    )
    expect(cleaned.nested.text).toBe('línea 1\nlínea 2')
    expect(cleaned.untouched).toBe('sin secuencias')
    expect((cleaned.panel as PanelInstance).id).toBe('panel-abc123')
  })
})
