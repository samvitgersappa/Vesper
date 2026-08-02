"""Plain-data automation jobs (plan.md §12).

Everything here is a plain scheduled worker — NO LLM in the loop. Reasoning jobs
(Morning Brief, Daily Journal Questionnaire, Evening/Weekly/Monthly Review,
Knowledge Architect judgment calls) are Hermes Agent cron skills under
`hermes-config/cron/`, never here.

Each job is a self-contained async or sync function registered in
`backend/automation/scheduler.py`. Jobs that need the DB use the shared async
session factory; jobs that are pure filesystem (vault) run sync.
"""

# Packages in this directory:
#   - finance.py        market data / factors / paper-trade EOD
#   - graph_analytics.py nightly network-science pass over the universal graph
#   - knowledge_architect.py mechanical batch tier (dedup, tagging, re-file)
#   - crm_followups.py  due-reminder sweep → notification
#   - rss.py            RSS fetch → capture routing
#   - vault_publish.py  daily git push of the vault + Quartz rebuild (addendum §7)
#   - hermes_mirror.py  mirror Hermes Agent audit logs into `hermes` schema (§13)
#   - notification.py   "what matters" triage + Telegram delivery (addendum §11)
