---
name: osmind
description: Use when the user wants to know which open-source issues are worth contributing to right now — e.g. "跑一下 osmind", "看看关注的仓库有什么能贡献的", "osmind report", "有没有适合我上手的 issue". Fetches recent issues from the user's watched repos, judges contributability against their resources/interests plus objective signals, and produces a ranked shortlist + macOS notification.
---

# osmind

A stateless contribution radar. Every run is a fresh judgment of what's live right
now in the user's watched repos — no memory of past runs. **You** are the judge:
fetch the issues, weigh them against the user's resources and interests plus the
objective facts, and hand back a short, honest, actionable shortlist.

## Inputs

Read the profile from `~/.config/osmind/profile.yaml`. It has:
`interests`, `skills`, `resources` (gpus/time), `watching` (repos, each with an
optional local `path`), and `output_dir`. No secrets — GitHub auth is `gh`'s job.

If `gh auth status` fails, stop and tell the user to run `gh auth login` first.

## Pipeline

### 1. Fetch — recent open issues per watched repo

For each repo in `watching`:

```bash
gh issue list --repo <owner/name> --state open --limit 30 \
  --json number,title,labels,assignees,comments,updatedAt,body
```

If a repo fetch fails, skip it and note it in the report — never abort the whole
run for one bad repo. Keep roughly the same count from each repo so a busy repo
doesn't crowd out a quiet one.

### 2. Collect objective signals

These are facts, not opinions — they drive the "already taken / infeasible" calls:

- **assignees**, **comment count**, **updatedAt** (staleness) come free from step 1.
- **Linked open PRs** — for any issue that otherwise looks promising, check whether
  someone already has an open PR on it:

  ```bash
  gh api repos/<owner/name>/issues/<number>/timeline \
    --jq '[.[] | select(.event=="cross-referenced") | .source.issue
           | select(.state=="open" and has("pull_request"))
           | {number, title}]'
  ```

  Don't run this for every candidate — only the ones you're about to recommend,
  to confirm they aren't occupied.
- **Local checkout** (optional): if a repo has a `path`, you may grep/read it to
  judge feasibility more concretely (does the fix touch code I understand? how big
  is the surface?). Use it when an issue is borderline — don't crawl it for all.

### 3. Judge — the actual product

Decide contributability by weighing three things together, NOT by literal
interest-keyword matching:

1. **资源约束** — does it need hardware the user doesn't have (H20 / Blackwell /
   GB200 / multi-node / AMD / NPU …)? The user has: see `resources`. If it needs
   more than they have → not feasible.
2. **兴趣与技能** — matches rank higher, but interest is not the only gate.
3. **客观事实** — has an open PR / is assigned / heavily参与 / long stale.

Rules:

- The recommended list holds only issues the user could **realistically pick up
  now**. 宁缺毋滥 — usually 5–10 is plenty. Each recommendation needs a concrete
  reason and a resource verdict; if evidence is thin, say so.
- Move the rest into a **collapsed skipped summary** — do NOT write full cards for
  them. Bucket each as: `resource` (hardware they lack), `occupied` (open PR /
  assigned, and you see no unique value they'd add), or `unclear` (too little info).
- **Serendipity (required): include 1–2 picks deliberately OUTSIDE the user's
  interests** — something you find genuinely interesting or worth doing and that is
  resource-feasible, to break them out of their bubble. Because of this, do not
  pre-filter candidates by interest; judge the whole pool.

### 4. Write report + notify

Write Markdown to `<output_dir>/reports/YYYY-MM-DD.md` (expand `output_dir`,
`mkdir -p` the `reports/` dir). Rerunning the same day overwrites that day's file.
Reports live here, NOT in the user's Obsidian vault — a triage sweep is inbox-grade,
not knowledge. Issues the user actually decides to work on graduate into the vault
by hand. Write the report 以中文为主.

Report shape:

```markdown
# osmind 贡献雷达 · YYYY-MM-DD

推荐 N 条 · serendipity M 条 · 跳过 K 条

## 推荐贡献

### [owner/name#123](https://github.com/owner/name/issues/123) — <title>
- 优先级: high|medium|low
- 理由: ...
- 资源: ...

（重复每一条；按优先级从高到低）

## 跳出兴趣（serendipity）

### [owner/name#456](...) — <title>
- 为什么值得一看（兴趣点之外）: ...
- 资源: ...

## 已跳过（K 条）
- 资源不可行: #a, #b, ...
- 已有人在做 / 已指派: #c, ...
- 信息不足: #d, ...

## 备注
- （任何 fetch 失败的仓库写在这里）
```

Then fire a macOS notification with the headline:

```bash
osascript -e 'display notification "推荐 N 条，serendipity M 条" with title "osmind 贡献雷达" subtitle "YYYY-MM-DD"'
```

Finally, print the report path and the one-line summary to the user.

## Scheduling (push)

This skill is pull (the user invokes it). To make it push on a schedule, a launchd
job can run it headless twice a week:

```bash
claude -p "run the osmind skill" --allowedTools "Bash,Read,Write"
```

Set that up only if the user asks — they may prefer to run it on demand.

## Don't

- Don't invent issues — only ever recommend ones returned by `gh`.
- Don't write to the Obsidian vault.
- Don't store state between runs — there is no memory, by design.
- Don't dump a long low-value list; the skipped summary is where the noise goes.
