---
name: study
description: "Study OS: mock tests, percentiles, exam readiness (Study module). New parity addition."
version: 0.1.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [study, exams, mock-tests, readiness]
    related_skills: []
---

# Study

New parity addition (no VesperAIOS equivalent). Serves the Study OS.

## When to Use

User asks about tests, mock tests, scores, percentiles, or exam readiness.

## Behavior

1. Call Study MCP tools: `study.list_tests()`, `study.mock_tests(test_id)`, `study.percentiles(test_id)`.
2. Summarize scores, percentiles, and readiness against the target exam date.

## MCP tools used

- `study.list_tests()`
- `study.mock_tests(test_id)`
- `study.percentiles(test_id)`
