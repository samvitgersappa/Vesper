---
name: morning-brief
description: "Morning Brief: cross-module daily summary with AI/tech research and verified cricket, football, and F1 updates. Reasoning job (plan §12)."
version: 0.3.0
author: Vesper
license: MIT
platforms: [linux, macos]
metadata:
  hermes:
    tags: [brief, daily, cross-module, scheduled]
    cron: "0 6 * * *"
    related_skills: []
---

# Morning Brief

Synthesized cross-module summary delivered proactively via Hermes Agent cron.

## When to Use

Triggered every day at 06:00 IST, including weekends.

## Behavior

Pull from module MCP tools and synthesize:
1. `finance.portfolio()` → NAV deltas.
2. `relationship.search()` / due contacts → CRM health/overdue.
3. `journal.get_entry()` → journal streak.
4. `study.list_tests()` → study progress.
5. `calendar.on_this_day()` → an "On this day" line.
6. Web/browser search → a high-signal AI and technology pulse.
7. Web/browser search → one worthwhile research-paper breakdown when available.
8. Web/browser search → verified cricket, football, and Formula 1 updates.

## AI and Technology Pulse

- Search the last 24–48 hours, preferring primary sources (company/research lab
  announcements, official changelogs, regulators) and reputable reporting.
- Select at most 3 items across AI, developer tools, semiconductors, security,
  and major technology policy. Avoid generic funding/product SEO stories.
- For each item give: `what happened`, `why it matters`, and the source name.
- Include the publication date or relative age. Do not repeat a story already
  covered in the immediately preceding brief unless there is a material update.

## Paper of the Day (REQUIRED — always include a link)

- EVERY morning brief MUST include a "Paper of the Day" with a **direct,
  openable link** Samvit can click to read as PDF or on arXiv. Prefer the
  arXiv abstract page (https://arxiv.org/abs/XXXX.XXXXX) and/or the PDF
  (https://arxiv.org/pdf/XXXX.XXXXX). A paper mentioned without a clickable
  link is a failed brief — always attach the URL.
- Prefer recent arXiv, conference, or lab releases with a meaningful result or
  a useful connection to Vesper, data systems, AI, or software engineering.
- Explain in plain language: problem, core idea, result, limitation, and one
  practical takeaway. Keep it to 4–6 sentences.
- Do not present a preprint as peer-reviewed, and do not imply production-ready.
- IF no genuinely newsworthy paper surfaced that day, DO NOT omit the section —
  instead surface one solid recent paper from the last ~30 days (arXiv cs.LG /
  cs.AI / cs.DB / cs.DC) and label it "Recent read" rather than "new". The link
  requirement is non-negotiable: a morning brief without a paper link is
  incomplete.

## Sports Snapshot

- Search for results and major upcoming fixtures/races from the last 24 hours
  and next 24 hours. Use official competition sites first, then trusted
  specialist sources such as ESPNcricinfo, BBC Sport, or Autosport.
- Include one compact line each for **Cricket**, **Football**, and **F1**.
- Report completed results with teams/drivers, score or finishing order, and
  competition. For upcoming events, include the start time in IST.
- Prioritize India-relevant or globally significant events. If a sport has no
  verified material update, say `No major verified update` for that sport; do
  not fill space with speculation or stale results.
- Never infer a live score, injury, transfer, lineup, or race result from an
  undated snippet. If web retrieval is unavailable, omit the affected detail
  and state that it could not be verified.

Deliver a concise natural-language brief in this order: personal dashboard,
AI/tech pulse, paper of the day, sports snapshot, then "On this day". Keep the
whole message skimmable (roughly 400–700 words); link or name sources inline and
avoid repeating raw tool output.

End with the "On this day" line:
- Call `calendar.on_this_day()` with no arguments (defaults to today).
- If `count == 0`, omit the line entirely (no filler).
- Otherwise render the most notable 1–2 items as
  `On this day (MM-DD): <year> — <title>`.
- Prefer journal entries and life events over routine interactions when
  choosing what to surface.
