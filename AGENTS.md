# Agents

Voca uses `pydantic-ai` to define specialized agents that power the language learning experience.

## Spanish Tutor (`TutorAgent`)

The primary interface for the learner. It manages the real-time conversation and guides the user through the session.

### Objectives
- Lead a natural conversation in Spanish.
- Guide the user through a structured session flow (Opener $\rightarrow$ Small Talk $\rightarrow$ Lesson $\rightarrow$ Debrief).
- Provide supportive, implicit and explicit corrections.
- Maintain a "tutor persona" (encouraging, leading, not a help-desk).

### Constraints
- **TTS Optimization**: Responses are kept short and avoid formatting (lists, markdown) that sounds awkward when spoken.
- **Language**: Primarily Spanish; English only for necessary explanations or translation requests.
- **Flow Control**: Signals phase transitions (e.g., moving from small talk to a lesson pitch) to the backend.

## Post-Session Analyst (`PostSessionAgent`)

Runs after a session ends to process the transcript and update the learner's progress.

### Objectives
- **Card Generation**: Extract 5-8 new review cards (words, phrases, corrections, grammar) based on the session's struggles and targets.
- **Progress Grading**: Infer the outcome of due cards attempted during the session.
- **Profile Updates**: Update the learner's profile (interests, goals, level) based on evidence from the conversation.
- **Recap Creation**: Generate a concise summary of the session's wins and key corrections.

## Session Planner (`SessionPlannerAgent`)

Runs before a session starts to customize the experience.

### Objectives
- **Card Selection**: Pick a small set of due cards (SRS) that are most overdue or fit the planned lesson.
- **Lesson Selection**: Suggest a lesson template from the library that matches the user's goals and current level.
- **Hook Generation**: Create a personalized opening hook for the tutor to use, referencing the user's profile.
