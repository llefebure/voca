import { describe, expect, it } from 'vitest'

import { LESSON_TEMPLATES, lessonTemplateBlurb, lessonTemplateName } from '@/lib/lesson-templates'

describe('lesson template metadata', () => {
  it('covers the six v1 templates, mirroring the backend catalog', () => {
    expect(LESSON_TEMPLATES.map((t) => t.code)).toEqual([
      'role_play',
      'reading_discussion',
      'dialogue_gaps',
      'story_telling',
      'explain_describe',
      'sentence_sprint',
    ])
  })

  it('lessonTemplateName maps known templates and falls back to "Lesson"', () => {
    expect(lessonTemplateName('role_play')).toBe('Role Play')
    expect(lessonTemplateName('reading_discussion')).toBe('Reading + Discussion')
    expect(lessonTemplateName('menu_role_play')).toBe('Lesson')
    expect(lessonTemplateName(null)).toBe('Lesson')
    expect(lessonTemplateName('')).toBe('Lesson')
  })

  it('lessonTemplateBlurb explains unknown templates generically', () => {
    expect(lessonTemplateBlurb('role_play')).toBe('Act out a scene together')
    expect(lessonTemplateBlurb('mystery')).toBe('A structured exercise')
  })
})
