# Simplify Tutor Agent and Implement Streaming

## Context
The goal is to simplify the `spanish_tutor` agent by removing structured output and phase-based logic, turning it into a simple conversational partner. Additionally, we want to improve the user experience by streaming the tutor's responses to the frontend using Server-Sent Events (SSE).

## Approach
1. **Tutor Agent Simplification**:
   - Remove the `TutorResponse` model.
   - Remove the phase-based system prompt logic.
   - Update the agent definition to return plain text.
   - Simplify the system prompt to a basic teacher persona.
2. **Backend Streaming Implementation**:
   - Update the `/chat` endpoint in `src/voca/main.py` to return a `StreamingResponse`.
   - Use `spanish_tutor.run_stream()` to get a stream of tokens.
   - Format the stream as SSE (`data: <token>\n\n`).
3. **Frontend Streaming Integration**:
   - Update `frontend/app/page.tsx` to handle the SSE stream using the `ReadableStream` API.
   - Implement a mechanism to update the chat history in real-time as tokens arrive.

## Files to modify
- `src/voca/agents/tutor_agent.py`
- `src/voca/main.py`
- `frontend/app/page.tsx`

## Reuse
- Use `FastAPI.responses.StreamingResponse` for the backend stream.
- Use `pydantic_ai`'s `.run_stream()` method for agent streaming.

## Steps
- [x] **Backend: Update Tutor Agent**
    - [ ] Remove `TutorResponse` and `TutorDeps` if no longer needed (or simplify them).
    - [ ] Remove `phase_instructions` from `tutor_system_prompt`.
    - [ ] Simplify `spanish_tutor` agent definition (remove `output_type`).
- [x] **Backend: Implement SSE in `/chat` endpoint**
    - [ ] Change return type to `StreamingResponse`.
    - [ ] Implement an async generator that calls `spanish_tutor.run_stream()` and yields SSE formatted data.
    - [ ] Ensure session and transcript updates still happen (either before streaming starts or after it ends).
- [x] **Frontend: Implement Stream Reading**
    - [ ] Update `sendMessage` to use `response.body.getReader()`.
    - [ ] Decode the stream and parse SSE `data:` blocks.
    - [ ] Update the state of the last message in `chatHistory` as tokens arrive.

## Verification
- [x] Start a chat session and verify the tutor responds as a simple teacher without phase transitions.
- [x] Verify that tokens appear one by one in the UI instead of waiting for the full response.
- [x] Check that the conversation is still correctly saved to the Supabase `transcripts` table.
