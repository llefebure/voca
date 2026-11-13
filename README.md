# Voca

Voca is an AI-powered language learning experience designed to make acquisition natural, structured, and personalized. The interface is English; the target language is configurable per user (Spanish is supported today, more planned). It combines real-time conversational tutoring with a sophisticated post-session analysis loop to ensure continuous progress.

## 🚀 Overview

Voca moves beyond simple chatbots by implementing a structured session flow powered by specialized AI agents. Instead of unstructured chatting, Voca guides learners through a designed pedagogy:
**Opener $\rightarrow$ Small Talk $\rightarrow$ Lesson $\rightarrow$ Debrief**.

## 🧠 The Agent Architecture

Voca leverages `pydantic-ai` to coordinate three primary agents:

### 1. Session Planner Agent (`session_planner_agent`)
Before a session begins, this agent:
- Analyzes the user's current profile and goals.
- Selects due SRS (Spaced Repetition System) cards, by ID.
- Picks a lesson template and instantiates it on the fly (role play, reading comprehension, free conversation).
- Generates a personalized "hook" to start the conversation.

### 2. Tutor Agent (`tutor_agent`)
The primary interface for the learner, responsible for:
- Leading a natural conversation in the learner's target language.
- Guiding the conversation through the session plan's lesson, when one exists.
- Providing supportive, implicit, and explicit corrections.
- Optimizing responses for Text-to-Speech (TTS).

### 3. Post-Session Analyst Agent (`post_session_agent`)
After the session ends, this agent processes the transcript to:
- **Generate Review Cards**: Extract new words, phrases, and grammar points into SRS cards.
- **Grade Progress**: Evaluate the learner's performance on attempted cards.
- **Update Profile**: Evolve the learner's profile (interests, level) based on evidence.
- **Create Recap**: Generate a summary of wins and key corrections.

## 🛠 Tech Stack

- **Backend**: 
  - `Python` / `FastAPI`
  - `pydantic-ai` (Agent orchestration)
  - `Ollama` (Local LLM serving)
  - `Supabase` (Database, Authentication, Storage)
  - `FSRS` (Free Spaced Repetition Scheduler for card reviews)
- **Frontend**: 
  - `Next.js` / `React` / `TypeScript`
  - `Tailwind CSS`

## 📂 Project Structure

```text
.
├── frontend/           # Next.js application
├── src/
│   └── voca/
│       ├── agents/     # Pydantic-AI agent definitions
│       ├── models/    # Data models and schemas
│       └── services/   # LLM, SRS, and Supabase integrations
└── supabase/          # Database migrations and configurations
```

## ⚙️ Setup & Installation

### Prerequisites
- Python 3.12+
- Node.js 18+
- Ollama (running locally)
- Supabase account/instance

### Backend Setup
1. Navigate to `src/voca`.
2. Create a `.env` file with the following:
   ```env
   SUPABASE_URL=your_supabase_url
   SUPABASE_KEY=your_supabase_anon_key
   LLM_BASE_URL=http://localhost:11434/v1
   ```
3. Install dependencies and run:
   ```bash
   pip install -r requirements.txt
   python main.py
   ```

### Frontend Setup
1. Navigate to `frontend/`.
2. Install dependencies:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev
   ```

## 📈 Session Lifecycle
1. **Plan**: `POST /sessions/plan` → `session_planner_agent` picks the lesson and cards (the frontend calls this right after the session starts).
2. **Chat**: `POST /chat` → `tutor_agent` interacts with the user.
3. **End**: `POST /sessions/end` → `post_session_agent` updates the learner's cards and profile.
