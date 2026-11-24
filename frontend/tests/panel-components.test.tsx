import * as React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { PanelCanvas, PanelRecord } from '@/components/panel/panel-components'
import type { PanelInstance } from '@/lib/panel-events'
import { cleanEscapedText } from '@/lib/panel-events'

afterEach(cleanup)

const MENU_MD = '**La Carta**\n\n| Plato | Precio |\n| :--- | :--- |\n| Tacos | 60 |'

function menuPanel(overrides: Partial<PanelInstance> = {}): PanelInstance {
  return {
    id: 'panel-abc123',
    title: 'Carta del día',
    markdown: MENU_MD,
    ...overrides,
  }
}

describe('PanelCanvas', () => {
  it('renders the panel markdown as a real table, with a working close button', () => {
    const onClose = vi.fn()
    render(<PanelCanvas panel={menuPanel()} onClose={onClose} />)
    expect(screen.getByTestId('panel-canvas')).toBeVisible()
    expect(screen.getByText('Carta del día')).toBeVisible()
    expect(screen.getByRole('table')).toBeVisible()
    fireEvent.click(screen.getByTestId('panel-close'))
    expect(onClose).toHaveBeenCalledTimes(1)
  })

  it('renders the markdown faithfully: headings, subheadings, and single newlines', () => {
    const { container } = render(
      <PanelCanvas
        panel={{
          ...menuPanel(),
          markdown:
            '# Historia\n## El primer día\nMatteo llegó temprano.\nNo encontró su café.\n\n### El canal',
        }}
      />,
    )
    // Header and subheader characters become real heading levels.
    expect(screen.getByRole('heading', { level: 1, name: 'Historia' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 2, name: 'El primer día' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 3, name: 'El canal' })).toBeVisible()
    // Single newlines inside a paragraph render as line breaks, not spaces:
    // both lines share one paragraph, separated by <br>.
    const body = container.querySelector('[data-testid="panel-canvas"] .prose p') as HTMLElement
    expect(body).not.toBeNull()
    expect(body.querySelector('br')).not.toBeNull()
    expect(body.textContent).toContain('Matteo llegó temprano.')
    expect(body.textContent).toContain('No encontró su café.')
  })

  it('decodes stored literal escapes before rendering', () => {
    render(
      <PanelCanvas panel={{ ...menuPanel(), markdown: '**Tacos**\\n\\n| Plato |\\n| :--- |' }} />,
    )
    // The literal sequence never reaches the DOM: the table renders.
    expect(screen.getByRole('table')).toBeVisible()
  })

  it('omits the close button when the canvas is not dismissible', () => {
    render(<PanelCanvas panel={menuPanel()} />)
    expect(screen.queryByTestId('panel-close')).toBeNull()
  })
})

describe('PanelRecord', () => {
  it('collapses by default and expands to the markdown content on click', () => {
    render(<PanelRecord panel={menuPanel()} />)
    expect(screen.queryByText('La Carta')).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: /Carta del día/ }))
    expect(screen.getByText('La Carta')).toBeVisible()
    expect(screen.getByRole('table')).toBeVisible()
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
