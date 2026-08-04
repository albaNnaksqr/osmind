# osmind

**osmind is a Claude Code skill for finding open-source issues that are actually
worth your time right now.**

Ask it ("跑一下 osmind" / "看看有什么能贡献的") and it runs a contribution radar over
the repos in your profile. It fetches recent open issues, checks whether the work
is already occupied or stale, weighs each issue against your interests, skills,
GPU/time resources, and local verifiability, then writes a short ranked Markdown
report plus a macOS notification.

The goal is not "find issues with matching keywords." The goal is: **give me a
small set of contribution candidates I can realistically pick up and prove.**
osmind also includes 1-2 serendipity picks outside your stated interests so the
radar does not become a filter bubble.

Personal tool. One user, one profile. No database, no memory of past decisions.
Every run is a fresh judgment of what's live right now.

## What it does

- Fetches recent open issues from watched GitHub repos with `gh`.
- Checks objective signals: assignees, comment count, staleness, linked PR state,
  reverse searches over open PRs, author intent, finalist comment threads, and
  one-hop proxy occupancy.
- Optionally reads local checkouts when `watching[].path` exists, so the agent can
  judge whether the likely fix is in familiar, testable code.
- Ranks by **verifiability first**: self-verifiable work beats impressive issues
  the user cannot prove fixed on their own hardware.
- Writes a Chinese Markdown report to `<output_dir>/reports/YYYY-MM-DD.md` and
  sends a macOS notification.

## Example output

See [`examples/report-2026-07-01.md`](examples/report-2026-07-01.md) for a real
report snapshot. It shows the intended shape: a short recommendation list,
serendipity picks, collapsed skip buckets, and notes about why candidates were
downgraded.

## Why a skill (not a program)

Once osmind went stateless, it stopped needing to be a program. A stateless
"fetch → judge → present" pipeline is exactly what an agent does natively: the
skill is the instructions, Claude Code is the runtime and the judge. That's
*better* judgment than the old fixed-prompt LLM call — the agent can `gh issue
view`, read the linked PR, even grep a local checkout — and there's almost no code
to maintain. It also means no secrets to manage: GitHub auth is `gh`'s job
(keychain), and there's no separate LLM key because the agent is the judge.

The pipeline lives in [`SKILL.md`](SKILL.md): `gh` fetch -> collect signals ->
judge -> Markdown report + macOS notify. Reports land in `output_dir/reports/`,
never the Obsidian vault — a triage sweep is inbox-grade, not knowledge.

## Setup

```bash
gh auth login          # one-time; token goes to the macOS keychain
```

Copy [`profile.yaml.example`](profile.yaml.example) to `~/.config/osmind/profile.yaml`
and fill in interests / skills / resources / watched repos / output_dir. No keys.

Install the skill (symlink so git stays the source of truth):

```bash
ln -s ~/workspace/osmind ~/.claude/skills/osmind
```

Then in Claude Code: *"跑一下 osmind"*.

### Scheduled push (installed)

The skill is pull; the push is a launchd job that runs it headless Mon/Thu 09:00:

- `~/Library/LaunchAgents/com.osmind.radar.plist` — the schedule (Weekday 1 & 4, 09:00).
- `~/.config/osmind/run.sh` — wrapper: sets a full PATH for launchd, then runs
  `claude -p "run the osmind skill" --allowedTools "Bash Read Write Skill"`.
- `~/.cache/osmind/logs/osmind.log` — run log; `launchd.{out,err}` catch launchd-level errors.

Manage it:

```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.osmind.radar.plist  # load
launchctl kickstart -p gui/$(id -u)/com.osmind.radar                            # run now
launchctl bootout   gui/$(id -u)/com.osmind.radar                               # unload
```

## Legacy

Earlier forms are recoverable by tag:
- `v0-tui` — the TUI / Learning-Pack / Contribution-Radar shapes and the stateful
  decision-memory version.
- `v1-stateless-cli` — the stateless Python CLI (`osmind report` / `osmind profile`)
  with a baked-in DeepSeek judgment call, before this pure-skill rewrite.
