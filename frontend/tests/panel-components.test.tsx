import * as React from 'react'
import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { displayPanel, PanelPane } from '@/components/panel/panel-components'
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

function baseProps() {
  return {
    activeIndex: 0,
    onSelect: vi.fn(),
    collapsed: false,
    onToggleCollapse: vi.fn(),
  }
}

describe('PanelPane (expanded)', () => {
  it('renders the focused artifact markdown as a real table, fold button works', () => {
    const props = baseProps()
    render(<PanelPane panels={[menuPanel()]} {...props} />)
    expect(screen.getByTestId('panel-pane')).toBeVisible()
    expect(screen.getByText('Carta del día')).toBeVisible()
    expect(screen.getByRole('table')).toBeVisible()
    // No tabs when a single artifact exists.
    expect(screen.queryByRole('tab')).toBeNull()
    fireEvent.click(screen.getByTestId('panel-collapse'))
    expect(props.onToggleCollapse).toHaveBeenCalledTimes(1)
  })

  it('shows one tab per artifact when several exist, switching on click', () => {
    const props = baseProps()
    render(
      <PanelPane
        panels={[
          menuPanel(),
          { id: 'panel-b', title: 'El cuento', markdown: 'Había una vez…' },
        ]}
        {...props}
        activeIndex={1}
      />,
    )
    const firstTab = screen.getByRole('tab', { name: /Carta del día/ })
    expect(firstTab).toHaveAttribute('aria-selected', 'false')
    expect(screen.getByRole('tab', { name: /El cuento/ })).toHaveAttribute('aria-selected', 'true')
    expect(screen.getByText('Había una vez…')).toBeVisible()
    fireEvent.click(firstTab)
    expect(props.onSelect).toHaveBeenCalledWith(0)
  })

  it('renders the markdown faithfully: headings, subheadings, and single newlines', () => {
    const { container } = render(
      <PanelPane
        panels={[
          {
            ...menuPanel(),
            markdown:
              '# Historia\n## El primer día\nMatteo llegó temprano.\nNo encontró su café.\n\n### El canal',
          },
        ]}
        {...baseProps()}
      />,
    )
    // Header and subheader characters become real heading levels.
    expect(screen.getByRole('heading', { level: 1, name: 'Historia' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 2, name: 'El primer día' })).toBeVisible()
    expect(screen.getByRole('heading', { level: 3, name: 'El canal' })).toBeVisible()
    // Single newlines inside a paragraph render as line breaks, not spaces:
    // both lines share one paragraph, separated by <br>.
    const body = container.querySelector('[data-testid="panel-pane"] .prose p') as HTMLElement
    expect(body).not.toBeNull()
    expect(body.querySelector('br')).not.toBeNull()
    expect(body.textContent).toContain('Matteo llegó temprano.')
    expect(body.textContent).toContain('No encontró su café.')
  })
})

describe('PanelPane (collapsed)', () => {
  it('folds to a rail labeled with the focused artifact; clicking reopens', () => {
    const props = baseProps()
    render(<PanelPane panels={[menuPanel()]} {...props} collapsed />)
    expect(screen.getByTestId('panel-rail')).toBeVisible()
    expect(screen.queryByRole('table')).toBeNull()
    expect(screen.getByText(/Carta del día/)).toBeVisible()
    fireEvent.click(screen.getByTestId('panel-rail'))
    expect(props.onToggleCollapse).toHaveBeenCalledTimes(1)
  })
})

describe('displayPanel / cleanEscapedText', () => {
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

  it('displayPanel returns an escape-decoded panel', () => {
    const panel = displayPanel({ ...menuPanel(), markdown: '**Tacos**\\n\\n| Plato |\\n| :--- |' })
    expect(panel.markdown).toContain('**Tacos**\n\n')
  })
})
