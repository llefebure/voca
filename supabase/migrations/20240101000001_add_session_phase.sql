-- Add current_phase to sessions table
ALTER TABLE sessions ADD COLUMN current_phase TEXT DEFAULT 'opener';
