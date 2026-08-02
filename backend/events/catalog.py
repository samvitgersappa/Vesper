"""Event catalog — the events from plan.md §6 as constants/schemas.

Every module's MCP server manifest declares which events it publishes and which
it subscribes to; this file is the single source of truth for event names so
publishers and subscribers never disagree.
"""

# ── Event names (plan.md §6 catalog) ──────────────────────────────────
JOURNAL_CREATED = "JournalCreated"
PERSON_UPDATED = "PersonUpdated"
INTERACTION_LOGGED = "InteractionLogged"
TRADE_EXECUTED = "TradeExecuted"
PORTFOLIO_NAV_UPDATED = "PortfolioNAVUpdated"
KNOWLEDGE_INDEXED = "KnowledgeIndexed"
REMINDER_DUE = "ReminderDue"
CALENDAR_EVENT_CREATED = "CalendarEventCreated"
STUDY_COMPLETED = "StudyCompleted"
KNOWLEDGE_ARCHITECT_PASS_COMPLETED = "KnowledgeArchitectPassCompleted"
# ADDENDUM §2.7 — emitted by the Daily Journal Questionnaire job (full or
# midnight-deadline placeholder); Evening Review subscribes (event + fallback).
DAILY_JOURNAL_COMPLETED = "DailyJournalCompleted"
# Phase 9 addition — universal graph task entity.
TASK_UPDATED = "TaskUpdated"

EVENTS = {
    JOURNAL_CREATED: "Journal",
    PERSON_UPDATED: "Relationship",
    INTERACTION_LOGGED: "Relationship",
    TRADE_EXECUTED: "Finance",
    PORTFOLIO_NAV_UPDATED: "Finance",
    KNOWLEDGE_INDEXED: "Knowledge",
    REMINDER_DUE: "Automation",
    CALENDAR_EVENT_CREATED: "Calendar",
    STUDY_COMPLETED: "Study",
    KNOWLEDGE_ARCHITECT_PASS_COMPLETED: "Automation",
    DAILY_JOURNAL_COMPLETED: "Journal",
    TASK_UPDATED: "Calendar",
}


def all_events() -> tuple[str, ...]:
    """All cataloged event names."""
    return tuple(EVENTS)
