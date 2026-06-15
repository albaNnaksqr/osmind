# osmind

A scheduled, stateless contribution-radar for the open-source repos I follow.

Twice a week, osmind fetches recent issues from my watched repos, asks an LLM which ones are actually worth contributing to — judged against my GPU/time resources, my interests, and objective facts (is someone already on it, how busy, how stale) — and pushes me a short ranked shortlist as a Markdown report plus a macOS notification. It deliberately slips in 1-2 picks *outside* my interests so I don't get stuck in my own bubble.

Personal tool. One user, one profile. No database, no memory of past decisions — every run is a fresh judgment of what's live right now.

## Why stateless

An earlier version remembered my continue/defer/discard decisions and resurfaced issues when they changed. I cut all of it. The report only ever looks at the ~30 most recently active issues per repo — for a busy repo that's a thin, fast-churning slice, so remembering past judgments buys little: rejected issues churn out of the window on their own, and anything I start working on auto-drops because its PR/assignee shows up in the objective signals. The product is just the push.

## The report

`osmind report` (cron, e.g. Mon/Thu) does the whole loop, no persistence:

1. **fetch** recent open issues from each watched repo (list-only — robust on a slow network).
2. **collect signals** — for each candidate, the linked open PRs (someone already on it?), plus assignees / comment count / staleness that come free with the issue.
3. **judge** — one LLM call ranks contributability against my resources + interests + signals, drops what's infeasible or already taken into a collapsed "已跳过" summary, and picks 1-2 serendipity items outside my interests.
4. **write + notify** — a Markdown report at `output_dir/reports/YYYY-MM-DD.md`, and a macOS notification with the headline.

Reports live in osmind's own output dir, not a notes vault — a triage sweep is inbox-grade, not knowledge. Issues I actually decide to work on graduate into my vault as project notes, by hand.

If the LLM is unreachable the report degrades to a raw candidate list instead of crashing; if a repo fetch fails it's skipped with a note. Cron stays alive.

## CLI

```bash
osmind report           # the loop above (--no-notify to skip the notification, --json for machine output)
osmind profile          # show interests, skills, resources, watched repos
```

## Setup

```bash
pip install -e .          # deps: PyGithub, PyYAML (LLM calls go over stdlib urllib)
```

`profile.yaml` (see `profile.yaml.example`):

```yaml
interests: [sglang, slime, ai infra]
skills: [python]
resources:
  gpus: 1 x Nvidia-Spark
  time: part-time
watching:
  - repo: THUDM/slime
  - repo: sgl-project/sglang
output_dir: ~/workspace/osmind-packets   # reports/ written here
llm:                                       # required — the contributability judge
  base_url: http://localhost:30000/v1
  model: DeepSeek-V4-Pro
  api_key: sk-your-key-here
```

Set `GITHUB_TOKEN` (the fetch needs the API). Schedule Mon/Thu with launchd (or cron):

```cron
0 9 * * 1,4 cd ~/workspace/osmind && GITHUB_TOKEN=... .venv/bin/osmind report
```

## Legacy

The old TUI / Learning-Pack / Contribution-Radar shapes, and the stateful
decision-memory version, are tagged `v0-tui`.
