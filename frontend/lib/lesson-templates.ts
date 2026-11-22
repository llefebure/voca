// Lesson template display metadata, mirroring the backend's
// `services/lesson_templates.py` (keep in sync). The names are UI labels in
// English; the lesson material itself is written in the target language.

export const LESSON_TEMPLATES: { code: string; name: string; blurb: string }[] = [
  { code: 'role_play', name: 'Role Play', blurb: 'Act out a scene together' },
  { code: 'reading_discussion', name: 'Reading + Discussion', blurb: 'Read a text, talk about it' },
  { code: 'dialogue_gaps', name: 'Dialogue Gaps', blurb: 'Fill in the lines of a dialogue' },
  { code: 'story_telling', name: 'Storytelling', blurb: 'Tell a story, get feedback' },
  { code: 'explain_describe', name: 'Explain & Describe', blurb: 'Explain things that matter to you' },
  { code: 'sentence_sprint', name: 'Sentence Sprint', blurb: 'Quick-fire sentence building' },
]

export function lessonTemplateName(templateId?: string | null): string {
  return (
    LESSON_TEMPLATES.find((template) => template.code === templateId)?.name ?? 'Lesson'
  )
}

export function lessonTemplateBlurb(templateId?: string | null): string {
  return (
    LESSON_TEMPLATES.find((template) => template.code === templateId)?.blurb ??
    'A structured exercise'
  )
}
