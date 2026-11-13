// Central configuration for where Voca's services live.
// Per-language TTS models/voices live in `lib/languages.ts`.

/** FastAPI backend, reachable from the browser (CORS allows the Next.js origin). */
export const BACKEND_URL =
  process.env.NEXT_PUBLIC_BACKEND_URL ?? "http://localhost:8000"

/** Local Ollama server, reachable only from Next.js server routes (no CORS needed). */
export const OLLAMA_URL = process.env.OLLAMA_URL ?? "http://localhost:11434"
