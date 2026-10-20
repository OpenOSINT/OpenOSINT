-- Migration: add the waitlist table to an existing OpenOSINT Cloud database.
-- Idempotent — safe to run more than once.
--
--   heroku pg:psql -a your-app-name < db/migrations/0001_add_waitlist.sql
--
-- New installs don't need this file — db/init.sql already includes it.

CREATE TABLE IF NOT EXISTS waitlist (
    id            SERIAL      PRIMARY KEY,
    email         TEXT        NOT NULL UNIQUE,
    role          TEXT,
    use_case      TEXT,
    plan_interest TEXT,
    source        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
