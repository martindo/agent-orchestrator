# Agent Orchestrator — Improvement Backlog

## Prioritized Improvements

| # | Improvement | Impact | Effort | Status |
|---|---|---|---|---|
| 1 | **WebSocket event stream** — real-time push of work item status, agent activity, governance decisions to connected clients | High | Medium | Planned |
| 2 | **Agent-to-agent communication** — agents can request help from other agents mid-task (e.g., backend agent asks security agent to review) | High | Large | Planned |
| 3 | **Connector marketplace** — more built-in connectors: Jira, GitHub, Slack, email, S3, database query | High | Medium per connector | Planned |
| 4 | **Scheduled workflows** — trigger workflows on a cron schedule (e.g., nightly data quality checks) | Medium | Medium | Planned |
| 5 | **Multi-tenant isolation** — separate data, agents, and workflows per tenant for SaaS deployment | Medium | Large | Planned |
| 6 | **Agent cost optimization** — route simple tasks to cheaper models (Haiku), complex tasks to expensive models (Opus), automatically based on task complexity scoring | High | Medium | Planned |
| 7 | **Workflow branching** — conditional paths based on agent output (if confidence > 0.9 go to fast-track, else go to human review) — partially exists but could be richer | Medium | Medium | Planned |
| 8 | **Bulk work item import** — upload a CSV/JSON of 1000 work items instead of submitting one at a time | Medium | Small | Planned |
| 9 | **Dashboard with metrics** — visual charts showing throughput, success rate, average processing time, cost per item, SLA compliance | High | Medium | Planned |
| 10 | **Plugin SDK** — let developers write custom connectors, quality gates, and phase handlers as npm packages that plug into AO | High | Large | Planned |

## Key Design Notes

### Agent-to-Agent Communication (#2)
- During execution, an agent can emit a `REQUEST_ASSISTANCE` event with:
  - Target agent role (e.g., "security", "qa")
  - Question or review request
  - Context (the code or data being worked on)
- The orchestrator routes the request to an available agent of that role
- The assisting agent responds with findings/advice
- The original agent incorporates the response and continues
- All assistance requests logged in the audit trail
- Governance: some assistance patterns may require approval (e.g., security review)

### Agent Cost Optimization (#6)
- Each work item gets a complexity score based on: story points, description length, number of files involved, skill required
- Complexity → model mapping:
  - Simple (1-2 points, single file): Haiku/small model ($0.01/task)
  - Medium (3-5 points, 2-5 files): Sonnet/medium model ($0.05/task)
  - Complex (5+ points, 5+ files, security/architecture): Opus/large model ($0.20/task)
- User can override per agent or per task type
- Dashboard shows cost savings vs. using Opus for everything
- Estimated 60-70% cost reduction for typical workloads

### Connector Priorities (#3)
Priority order for new connectors:
1. **GitHub** — create issues, PRs, read repos, review comments
2. **Jira** — create/update tickets, read sprint boards
3. **Slack** — send notifications, receive commands
4. **Email** — send alerts, receive work items via email
5. **S3/Storage** — upload/download artifacts
6. **Database** — query PostgreSQL/MySQL for data-driven workflows
7. **Webhook** — generic outbound HTTP calls

### Scheduled Workflows (#4)
- New config section in workflow.yaml:
  ```yaml
  schedules:
    - id: nightly-quality
      cron: "0 2 * * *"
      workflow: data-quality-check
      input: { source: "production_db", threshold: 0.95 }
    - id: weekly-report
      cron: "0 9 * * 1"
      workflow: generate-weekly-report
  ```
- Orchestrator runs a cron scheduler that submits work items at the configured times
- Dashboard shows upcoming scheduled runs and history
