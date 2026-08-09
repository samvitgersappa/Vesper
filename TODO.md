# Vesper TODO

This is the single authoritative backlog for unfinished work and research
validation. Update the checkbox when an item is complete:

- `[ ]` not started or incomplete
- `[-]` in progress or monitoring
- `[x]` complete and verified

Completed work should remain documented in the relevant implementation and
tests. Do not create another `TODO` or feature-tracker file; add new work here.

## P0: Memory and Recall

### [ ] Unified recall across every memory store

Build one `knowledge.recall_everything(query)` path that searches and merges:

- Obsidian vault notes and journal files.
- Postgres journal, CRM, calendar, study, finance metadata, and audit rows.
- LanceDB semantic records.
- Hermes/TencentDB Agent Memory, when configured.

Acceptance criteria:

- Results identify their source store and stable reference ID.
- Duplicate results are merged deterministically.
- A test proves recall survives an API, worker, and Hermes restart.
- Missing optional stores degrade with an explicit source-status warning.

### [ ] User-facing memory browser

Add a web and Hermes-accessible browser for stored memories. Each result should
show the source store, path/table, created/updated time, links, and available
edit/delete action. Include filters for vault, journal, CRM, spending, workout,
Hermes memory, and semantic index.

Acceptance criteria:

- A user can answer “where is this stored?” without inspecting the server.
- Delete/correction operations update every applicable index.
- Export and deletion actions are auditable and protected.

## P0: Finance Research Validation

These are research gates, not claims that a strategy has an investable edge.
Use free/open historical data where legally and technically practical, and
record source, date, coverage, and limitations with every result.

### [ ] Point-in-time Nifty universe data

- Acquire dated constituent snapshots from a lawful free source where possible.
- Store membership intervals in `index_membership`.
- Preserve the current static CSV only as a clearly labeled fallback.
- Test that a backtest sees only constituents known on that historical date.

### [ ] Survivorship-bias-free backtesting

- Run the same strategy using point-in-time constituents and the current static
  universe.
- Compare CAGR, Sharpe, max drawdown, turnover, hit rate, and trade count.
- Publish the data limitations and expected bias if historical membership cannot
  be obtained for a period.

### [ ] Walk-forward out-of-sample validation

- Define fixed train/test windows and never tune on test results.
- Run expanding-window and rolling-window variants.
- Report per-window and aggregate performance with costs and slippage.
- Store the exact code commit, data snapshot, and parameters for reproduction.

### [ ] Validate 3 versus 6 Layer-3 catalyst dimensions

- Run an identical point-in-time walk-forward experiment with the first three
  dimensions and with all six.
- Compare Sharpe, Calmar, drawdown, turnover, stability, and degradation rate.
- Keep the six-dimension version only if the additional dimensions improve
  out-of-sample results without unacceptable complexity or instability.

## P1: Pipeline Reliability

### [-] Monitor the catalyst breadth-to-screen timing gap

The current schedule has `compute_market_breadth` at 18:15 IST and
`catalyst_screen` at 18:20 IST on weekdays.

Complete this item when:

- Job duration and completion timestamps are visible in the dashboard.
- `catalyst_screen` records whether breadth data is fresh for the same run.
- A missed or stale breadth pass triggers a safe retry or honest degraded run.
- An alert is delivered when the five-minute budget is exceeded repeatedly.

## P1: VM Migration and Disaster Recovery

### [x] Document a complete migration plan

The following procedure is the canonical migration runbook. Test it on a
temporary VM before destroying the old one.

#### 1. Freeze and inventory the old VM

- Stop writes or announce a short maintenance window.
- Record the Git commit, `.env` variable names, hostname, and current service
  status. Never copy secrets into Git or a public issue.
- Run the Postgres dump, vault archive, and Hermes-state backup below.

#### 2. Back up the durable stores

```bash
mkdir -p /var/backups/vesper
docker compose exec -T postgres pg_dump -U vesper -d vesper \
  | gzip > /var/backups/vesper/postgres-$(date +%F).sql.gz
tar --exclude='.git' -czf /var/backups/vesper/vault-$(date +%F).tar.gz \
  -C "$HOME/Documents" KnowledgeVault
tar -czf /var/backups/vesper/hermes-$(date +%F).tar.gz \
  -C "$HOME" .hermes
cp .env /var/backups/vesper/vesper.env
sha256sum /var/backups/vesper/*
```

Store backups encrypted and off the old VM. Treat `.env`, Hermes state, and the
vault as confidential. DuckDB/LanceDB are rebuildable, but back them up if the
rebuild time or historical features matter.

#### 3. Create the new VM

- Use the same or newer supported Ubuntu release.
- Apply security updates, SSH keys, a firewall, swap, Docker, and a hostname.
- Point DNS/DuckDNS at the new VM only after HTTPS is ready.
- Clone the public repository and run `./start.sh --no-web` once to create the
  virtual environment and generated secrets.

#### 4. Restore configuration safely

- Copy the old `.env` through a secure channel, then rotate credentials if the
  old VM may have been compromised.
- Set the new `VESPER_DOMAIN` and Basic Auth password.
- Run `./start.sh --restart` so MCP definitions receive host-local credentials.

#### 5. Restore Postgres

```bash
gunzip -c /var/backups/vesper/postgres-YYYY-MM-DD.sql.gz \
  | docker compose exec -T postgres psql -U vesper -d vesper
./start.sh --restart
```

Do not use `--fresh` after restoring; it intentionally deletes the restored
Postgres data. Restore only into a new, verified database first when possible.

#### 6. Restore the vault and Hermes state

```bash
tar -xzf /var/backups/vesper/vault-YYYY-MM-DD.tar.gz -C "$HOME/Documents"
tar -xzf /var/backups/vesper/hermes-YYYY-MM-DD.tar.gz -C "$HOME"
chmod 700 "$HOME/.hermes" "$HOME/Documents/KnowledgeVault"
./start.sh --restart
```

If Hermes state is incompatible with the installed Hermes version, keep the
vault and Postgres restore, start with a new Hermes state database, and resync
the MCP servers and cron jobs.

#### 7. Verify before cutover

- Check API, Caddy HTTPS, Basic Auth, Postgres, Redis, Quartz, and Telegram.
- Run `hermes mcp test` for all eight Vesper servers.
- Verify graph, journal, expenses, account balances, and recent cron runs.
- Verify the vault and Hermes memory counts against the old VM.
- Switch DNS only after all checks pass, then keep the old VM powered off but
  recoverable until the next backup succeeds.

## P2: Net-Worth Extensions

### [ ] Add a net-worth layer only where it complements INDmoney

INDmoney should remain the source of truth for brokerage holdings and official
portfolio valuation. Vesper should avoid duplicating its broker integration
unless there is a clear benefit.

Potential useful additions:

- Consolidated snapshot of assets and liabilities outside INDmoney: cash,
  bank balances, EPF/PPF, gold, insurance value, loans, and credit cards.
- Monthly net-worth snapshots and a personal balance-sheet timeline.
- Goal tracking: emergency fund, education, travel, home, and retirement.
- Cash-flow forecasting from the spending system and recurring obligations.
- Tax-lot and realized-gain notes imported from statements, without live trading.
- Net-worth change explanations that reconcile market movement, savings,
  spending, and debt repayment.
- Privacy-preserving CSV/manual import rather than storing broker credentials.

Do not build a second live broker system unless INDmoney cannot provide a needed
view. The highest-value low-risk version is manual/CSV snapshots plus liabilities,
goals, cash flow, and explanations.

## Backlog Hygiene

- Keep this file as the only TODO/backlog file.
- Mark items `[-]` while actively monitored and add the evidence or issue link.
- Mark items `[x]` only after implementation, tests, and operational verification.
- Move historical rationale into `plan.md` or the relevant design document.
