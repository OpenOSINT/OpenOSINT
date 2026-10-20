-- OpenOSINT Cloud — database schema
-- Run once against your Heroku Postgres instance:
--   psql $DATABASE_URL -f db/init.sql

CREATE TABLE IF NOT EXISTS customers (
    api_key           TEXT        PRIMARY KEY,
    credits           INT         NOT NULL DEFAULT 0,
    plan              TEXT        NOT NULL DEFAULT 'payg',
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Customer BYOK keys, encrypted at rest with Fernet (CONFIG_ENCRYPTION_KEY).
-- Cascade delete removes keys when the customer row is deleted.
CREATE TABLE IF NOT EXISTS customer_keys (
    api_key          TEXT        NOT NULL REFERENCES customers(api_key) ON DELETE CASCADE ON UPDATE CASCADE,
    provider         TEXT        NOT NULL,
    secret_encrypted TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (api_key, provider)
);

-- OAuth login identities (GitHub / Google). Purely a web-dashboard login
-- layer on top of the api_key model — X-API-Key / MCP bearer auth never
-- reads this table. One OAuth identity links to at most one customer key
-- and vice versa (partial unique index below).
CREATE TABLE IF NOT EXISTS users (
    id                SERIAL      PRIMARY KEY,
    provider          TEXT        NOT NULL,
    provider_user_id  TEXT        NOT NULL,
    email             TEXT,
    customer_api_key  TEXT        REFERENCES customers(api_key) ON DELETE SET NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (provider, provider_user_id)
);

-- Enforces strict 1:0-or-1: a customer key can be linked to at most one user.
CREATE UNIQUE INDEX IF NOT EXISTS users_customer_api_key_idx
    ON users (customer_api_key)
    WHERE customer_api_key IS NOT NULL;

-- Pre-launch demand-validation signups for a future self-serve Cloud tier.
-- No payment processing, no IP address stored. email is lowercased by the
-- API before insert; the UNIQUE constraint is the duplicate-signup guard.
CREATE TABLE IF NOT EXISTS waitlist (
    id            SERIAL      PRIMARY KEY,
    email         TEXT        NOT NULL UNIQUE,
    role          TEXT,
    use_case      TEXT,
    plan_interest TEXT,
    source        TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
