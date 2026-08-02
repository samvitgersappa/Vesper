---
name: calendar
description: "Calendar: birthdays, interactions, exam dates, market dates (Calendar module). New parity addition."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [calendar, birthdays, events, reminders]
    related_skills: []
---

# Calendar

New parity addition (no VesperAIOS equivalent). Serves the Calendar module.

## When to Use

User asks what's coming up (birthdays, events, exam dates, market dates).

## Behavior

1. Call Calendar MCP tools: `calendar.events(from, to)`, `calendar.birthdays()`.
2. Summarize upcoming items chronologically.

## MCP tools used

- `calendar.events(from, to)`
- `calendar.birthdays()`
