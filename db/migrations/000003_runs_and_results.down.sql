BEGIN;

ALTER TABLE semesters DROP CONSTRAINT IF EXISTS semesters_published_run_fk;

DROP TABLE IF EXISTS run_violations;
DROP TABLE IF EXISTS calendar_sessions;
DROP TABLE IF EXISTS template_sessions;
DROP TABLE IF EXISTS section_assignments;
DROP TABLE IF EXISTS run_progress;
DROP TABLE IF EXISTS schedule_runs;

COMMIT;
