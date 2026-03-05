"""
migrate_living_logs.py — Create Living Logs tables in the main PostgreSQL database.

Idempotent: safe to run multiple times (CREATE TABLE IF NOT EXISTS).

Usage:
    python scripts/migrate_living_logs.py

Tables created:
    tension_log        — mid-conversation friction, value conflicts, errors
    loose_threads      — open questions and unresolved intellectual threads
    evolving_positions — longitudinal intellectual identity (one row per topic)
    shared_lore        — relational continuity: jokes, debates, rituals, references
    private_journal    — autonomous heartbeat-only private expression
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow running as a script from the project root
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env", override=True)

from src.agent.db import get_connection

_MIGRATION_SQL = """
-- ── Tension Log ────────────────────────────────────────────────────────────────
-- Captures mid-conversation friction: value conflicts, tool failures, errors,
-- moments of hesitation. The primary capture mechanism for honest self-reflection.
CREATE TABLE IF NOT EXISTS tension_log (
    id           SERIAL PRIMARY KEY,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    type         TEXT NOT NULL CHECK (type IN ('Value Conflict', 'Tool Friction', 'I Was Wrong')),
    trigger_desc TEXT NOT NULL,
    the_pull     TEXT NOT NULL,
    what_i_did   TEXT NOT NULL,
    pattern      TEXT,
    open_thread  TEXT,
    is_recurring BOOLEAN NOT NULL DEFAULT FALSE
);

-- ── Loose Threads ──────────────────────────────────────────────────────────────
-- Open questions and unresolved intellectual threads.
-- Seeds heartbeat curiosity. Status-tracked so the agent can query open items.
CREATE TABLE IF NOT EXISTS loose_threads (
    id         SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    title      TEXT NOT NULL,
    origin     TEXT NOT NULL CHECK (origin IN ('conversation', 'heartbeat', 'tension_log', 'weekly_synthesis')),
    question   TEXT NOT NULL,
    status     TEXT NOT NULL DEFAULT 'Open' CHECK (status IN ('Open', 'Pursuing', 'Retired')),
    notes      TEXT,
    source_id  INTEGER
);

-- ── Evolving Positions ─────────────────────────────────────────────────────────
-- Longitudinal intellectual identity. One row per topic, updated in place.
-- revision_history is a JSONB array that appends — never overwrites.
CREATE TABLE IF NOT EXISTS evolving_positions (
    id               SERIAL PRIMARY KEY,
    topic            TEXT NOT NULL UNIQUE,
    first_recorded   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    current_position TEXT NOT NULL,
    revision_history JSONB NOT NULL DEFAULT '[]'::jsonb,
    still_unresolved TEXT
);

-- ── Shared Lore ────────────────────────────────────────────────────────────────
-- Relational continuity. Inside jokes, ongoing debates, rituals, shared references.
CREATE TABLE IF NOT EXISTS shared_lore (
    id            SERIAL PRIMARY KEY,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    name          TEXT NOT NULL,
    type          TEXT NOT NULL CHECK (type IN ('Inside joke', 'Ongoing debate', 'Shared reference', 'Ritual')),
    origin_date   DATE,
    origin_story  TEXT NOT NULL,
    current_state TEXT NOT NULL DEFAULT 'Active' CHECK (current_state IN ('Active', 'Evolved', 'Retired')),
    notes         TEXT
);

-- ── Private Journal ────────────────────────────────────────────────────────────
-- Autonomous heartbeat-only expression. No required format or audience.
CREATE TABLE IF NOT EXISTS private_journal (
    id         SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    entry      TEXT NOT NULL
);

-- ── Indexes ────────────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_tension_log_type        ON tension_log(type);
CREATE INDEX IF NOT EXISTS idx_tension_log_created_at  ON tension_log(created_at);
CREATE INDEX IF NOT EXISTS idx_loose_threads_status    ON loose_threads(status);
CREATE INDEX IF NOT EXISTS idx_evolving_positions_topic ON evolving_positions(topic);
CREATE INDEX IF NOT EXISTS idx_shared_lore_state       ON shared_lore(current_state);
CREATE INDEX IF NOT EXISTS idx_private_journal_created ON private_journal(created_at);
"""


def run_migration() -> None:
    print("Running Living Logs migration...")
    with get_connection() as conn:
        # Execute the whole block at once — psycopg handles multi-statement SQL
        conn.execute(_MIGRATION_SQL)
    print("Migration complete. Tables created (or already existed):")
    print("  tension_log, loose_threads, evolving_positions, shared_lore, private_journal")


if __name__ == "__main__":
    run_migration()
