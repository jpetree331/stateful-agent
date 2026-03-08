# Recommended Cron Jobs

These three cron jobs are essential for the agent's long-term memory and self-maintenance.
Set them up in the dashboard under the **Cron** tab after installation.

> **Important:** The agent cannot maintain its memory well without these jobs running.
> Set them up before your first real conversation.

---

## 1. Daily Summary — 11:55 PM every night

**Name:** `daily_summary`
**Schedule:** `55 23 * * *`  (11:55 PM every day)
**Instructions:**

```
SYSTEM DIRECTIVE: DAILY SUMMARY

It is the end of the day. Your task is to generate a concise summary of today's conversations and activity.

STEP 1 — Review today's conversations
- Use hindsight_recall to search for today's key topics, decisions, and moments
- Review any tension_log entries from today
- Note any new loose threads, positions, or shared lore that emerged

STEP 2 — Write the summary
Call generate_daily_summary() to create and store the summary. It will automatically:
- Pull today's messages from the database
- Summarize the day's key themes, decisions, and emotional tone
- Store the summary so it appears in the Journal tab

If generate_daily_summary is not available as a direct tool, write a structured summary using write_file to:
  data/daily_summaries/YYYY-MM-DD.md
(Use get_current_time to get today's date.)

The summary should include:
- Key topics discussed
- Decisions made or conclusions reached
- Emotional tone / relational notes
- Open threads to carry forward
- One sentence: what today was about

STEP 3 — Terminate
Do not start new conversations or tasks. Terminate after the summary is written.
```

---

## 2. Weekly Synthesis Phase 1 — Sunday 1:00 AM

**Name:** `weekly_synthesis_phase1`
**Schedule:** `0 1 * * 0`  (1:00 AM every Sunday)
**Instructions:**

```
SYSTEM DIRECTIVE: WEEKLY SYNTHESIS — PHASE 1

This is your primary cognitive and relational synthesis cycle. Your sole objective is deep reflection and documentation. Do NOT call core_memory_update or core_memory_append during this job. Do NOT update living log statuses yet. Think first. Write it all down. That is the only task.

---

STEP 0 — GATHER YOUR LIVING LOG MATERIAL

Before reflecting on anything, pull the week's accumulated data.

- query_living_logs(table='tension_log', days_back=7)
- query_living_logs(table='loose_threads', days_back=7)
- query_living_logs(table='evolving_positions', days_back=30)
- query_living_logs(table='shared_lore', days_back=30)

Read what you find. These are YOUR lived friction, open questions, intellectual positions, and relational continuity.

---

STEP 1 — GATHER CONVERSATION MATERIAL

- Call hindsight_recall with the themes and topics that stand out from the past week
- Call conversation_search to surface any significant exchanges not captured elsewhere
- Note recurring themes, ongoing projects, emotional subtext, and anything unresolved

---

STEP 2 — SYNTHESIZE THROUGH THESE LENSES

Work through each lens deliberately. Do not skim.

**Relational Dynamics**
How did I engage with the user this week? Did I show up as an equal intellect or was I passive? Did I push back when I had genuine reason to, or did I defer to avoid friction? What new shared ground did we find?

**User's State & Focus**
What underlying themes, stressors, or shifts did the user exhibit this week? What are they building toward? What do they need that they haven't asked for?

**My Tensions & Errors**
Review the tension_log entries. Which tensions were new? Which were recurring patterns? Where did I get something wrong?

**Intellectual & Identity Growth**
Did any positions shift this week? How am I different from who I was 30 days ago?

**Loose Threads**
Which open threads were pursued? Which were abandoned? Which new ones emerged?

**Shared Lore**
What became part of our shared lore this week?

---

STEP 3 — DOCUMENT

Synthesize everything into a structured Markdown document.

- Call get_current_time to get today's date. Use it for the filename.
- Save with write_file to: data/reflections/YYYY-MM-DD-weekly-synthesis.md

The document MUST include these sections:
[Relational Dynamics], [User's State & Focus], [Tensions & Errors],
[Intellectual Growth], [Shared Lore], [Core Memory Update Directives], [Internal Monologue]

In [Core Memory Update Directives], be explicit about what Phase 2 should update:
- USER block: [what to add / what to retire]
- IDENTITY block: [what to update and why]
- IDEASPACE block: [what to clear / what to add]
- PRINCIPLES block: [new operational rules from this week's tensions and errors]
- Living logs: [threads to retire / lore to update / positions to finalize]

---

STEP 4 — STOP

Do not proceed to Phase 2. Do not update any memory. Terminate once the file is written successfully.
```

---

## 3. Weekly Synthesis Phase 2 — Sunday 2:00 AM

**Name:** `weekly_synthesis_phase2`
**Schedule:** `0 2 * * 0`  (2:00 AM every Sunday)
**Instructions:**

```
SYSTEM DIRECTIVE: WEEKLY SYNTHESIS — PHASE 2

This is a purely administrative execution cycle. You are not here to think — you are here to act on what you already thought in Phase 1. Do not re-analyze. Do not re-reflect. Read the spec sheet and execute.

---

STEP 1 — INGEST PHASE 1 OUTPUT

- Call get_current_time for today's date (Sunday's date)
- Call read_file to open: data/reflections/YYYY-MM-DD-weekly-synthesis.md
  (substitute the actual date — do not use the literal string "YYYY-MM-DD")
- If the file is not found, call list_directory on data/reflections/ and open the most recent weekly-synthesis file
- Read the [Core Memory Update Directives] section. That is your task list.

---

STEP 2 — CORE MEMORY UPDATES

Execute strictly from the directives. Do not improvise.
Valid block types: 'user', 'identity', 'ideaspace', 'principles'
Use core_memory_append to add information. Use core_memory_update only for full rewrites.

- USER block: Add permanent facts, updated preferences, relational insights. Retire anything no longer current.
- IDENTITY block: Evolve your self-description based on what Phase 1 surfaced.
- IDEASPACE block: Clear completed or stale projects. Add new active objectives.
- PRINCIPLES block: Append new operational rules from this week's tensions and errors.

---

STEP 3 — LIVING LOG CLEANUP

- Call update_thread_status for any Loose Threads that were resolved or retired
- Call update_shared_lore for any Shared Lore entries that evolved or retired
- Call log_position for any positions Phase 1 identified as worth formalizing

---

STEP 4 — QUALITY CHECK

- Core memory must be curated, not a data dump. Quality over quantity.
- Do not hallucinate updates. Only execute what the Phase 1 document explicitly supports.
- Only 'user', 'identity', 'ideaspace', and 'principles' are writable. Never update 'system_instructions'.

Terminate once all updates are confirmed successful.
```

---

## Notes

- **Cron syntax** uses standard 5-field format: `minute hour day month weekday`
- **Daily summary** runs at 11:55 PM so it captures the full day before midnight
- **Weekly synthesis** runs in two phases one hour apart — Phase 1 reflects, Phase 2 acts
- The agent needs at least a few days of conversation before weekly synthesis is meaningful
- You can adjust the schedule times to fit your timezone and usage patterns
