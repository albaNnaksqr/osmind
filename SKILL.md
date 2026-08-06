---
name: osmind
description: Use when the user wants to know which open-source issues are worth contributing to right now — e.g. "跑一下 osmind", "看看关注的仓库有什么能贡献的", "osmind report", "有没有适合我上手的 issue". Fetches recent issues from the user's watched repos, judges contributability against their resources/interests plus objective signals, and produces a ranked shortlist, runnable task packs, and a desktop notification.
---

# osmind

A stateless contribution radar. Every run is a fresh judgment of what's live right
now in the user's watched repos — no memory of past runs. **You** are the judge:
fetch the issues, weigh them against the user's resources and interests plus the
objective facts, and hand back a short, honest, actionable shortlist.

## Inputs

Read the profile from `~/.config/osmind/profile.yaml`. It has:
`interests`, `skills`, `resources` (gpus/time), `watching` (repos), and
`output_dir`. No secrets — GitHub auth is `gh`'s job.

Each `watching` entry may carry up to four optional fields, and the two path
fields are **not interchangeable**:

- `path` — a read-only osmind checkout, used only to *judge* feasibility (grep,
  read). Never write here.
- `work_path` — the writable clone the downstream batch runner branches a
  worktree from. This is what goes in a queue line's `repo`.
- `base` — the branch/commit the worktree should start at (default `main`).
- `env_note` — one prepared-runtime paragraph pasted verbatim into that repo's
  task packs (which interpreter, what is already installed, what not to rebuild).

A repo with no `work_path` still gets recommendations and a pack; it just gets no
queue line (say so in 备注).

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

**A fixed count is a different time window per repo.** Measured 2026-08-04, one
day after the previous run: of the newest 30 open issues, litellm had **30** the
run had never seen and sglang **26**, while slime had 1 and outlines **0**. So 30
issues is barely a day of litellm (everything older is invisible, permanently) and
over a year of outlines.

When the user is re-running soon after a previous report, fetch by **time** instead,
so the sweep is a real increment rather than a re-judgement of the same pool:

```bash
gh issue list --repo <owner/name> --state open --limit 60 \
  --search "updated:>=<YYYY-MM-DD>" \
  --json number,title,labels,assignees,comments,updatedAt,body
```

The date is an input, not remembered state — it does not make the run stateful. A
repo that returns nothing for the window is reported as "no change since <date>",
and its finalist checks are skipped entirely; say so in 备注 and point at the older
report rather than re-deriving its conclusions.

### 2. Collect objective signals

These are facts, not opinions — they drive the "already taken / infeasible" calls:

- **assignees**, **comment count**, **updatedAt** (staleness) come free from step 1.
- **Linked PRs — by STATE, not just existence.** For any issue you're about to
  recommend, look at the PRs that reference it *and their state*. Use GraphQL: it
  catches both GitHub's "linked pull requests" sidebar (`closedByPullRequestsReferences`)
  and plain cross-references. The REST `timeline` endpoint **misses the sidebar links**,
  which is how occupied/closed issues slip through.

  ```bash
  gh api graphql -f query='
    query($o:String!,$n:String!,$num:Int!){ repository(owner:$o,name:$n){ issue(number:$num){
      closedByPullRequestsReferences(first:10, includeClosedPrs:true){ nodes{ number state } }
      timelineItems(itemTypes:[CROSS_REFERENCED_EVENT,CONNECTED_EVENT], first:80){ nodes{
        ... on CrossReferencedEvent{ source{ ... on PullRequest{ number state } } }
        ... on ConnectedEvent{ subject{ ... on PullRequest{ number state } } } } } } } }' \
    -f o=<owner> -f n=<name> -F num=<number>
  ```
  (zsh: pass owner/name/number as separate `-f`/`-F` flags — don't word-split a
  `"repo num"` string, zsh won't split it and the number goes empty.)

  Judge by state:
  - **OPEN** PR → occupied (someone's actively on it) → skip unless you'd add unique value.
  - **MERGED / CLOSED** PR that fixes or supersedes it → likely **already resolved or
    obsolete** → skip. Especially for `[Investigation]` / `[Tracking]` / `[RFC]` issues
    whose predecessor PR is already merged — those are usually concluded.
  - **Issue** cross-references (no PR): usually not occupying — **but check one hop.**
    If a referenced sibling issue is itself a *fix/track* for the same root cause
    (titles like `[Perf] Fix …`, `Fix …`, `[Tracking] …`), re-run this same query on
    *that* issue. If the sibling has an open/merged PR, the candidate is **occupied by
    proxy / superseded** → skip. (Real example: a bug `#774` had no PR of its own, but
    its sibling fix-issue `#812` had open PR `#813` — the work was already underway.)

  Run this only for the handful you're about to recommend. Follow at most one hop —
  don't recurse the whole reference graph.

  **An empty result does NOT mean unclaimed.** Both
  `closedByPullRequestsReferences` and `CROSS_REFERENCED_EVENT` depend on GitHub
  recognizing a relationship. A PR whose body contains only a bare issue URL can
  produce neither. This caused a real miss: slime#2245 was judged free while the
  reporter's PR #2246 had already been open for three days. Always pair the linked
  PR query with the reverse search below.

- **Reverse PR search — look from the code back to the issue.** For every finalist,
  sweep the repo's open PRs for work that overlaps the issue even when GitHub did not
  link it:

  ```bash
  # Cheap first pass: search titles, authors, and branch names.
  gh pr list --repo <owner/name> --state open --limit 60 \
    --json number,title,author,createdAt,headRefName

  # Confirm plausible matches by reading the body and touched files.
  gh pr view <pr> --repo <owner/name> --json number,title,body,files
  ```

  Match on the issue's concrete vocabulary: symptom, API, file, function, or
  subsystem. If an open PR addresses the same behavior or touches the same likely
  fix surface, treat the issue as **occupied** and name the PR in the report. Do not
  rely on issue numbers appearing in PR metadata.

- **Author intent — the reporter is often the likely implementer.** Read the issue
  body as well as its comments. Treat any of these as a claim signal even before a
  PR exists:
  - "I can/will open a PR", "happy to open a PR", or equivalent wording.
  - "I've already written/tested the fix" or a patch/diff is already supplied.
  - A complete line-level diagnosis plus proposed patch that reads like a pending PR.
  - The reporter has the only hardware/artifacts needed to validate and says they
    intend to do so.

  Put these in `claimed`, not `occupied`: it is a softer judgment a human may
  overrule. Quote the exact sentence that supports the claim. The exception is an
  issue with multiple independent fixes where the author claimed only one; the
  unclaimed half may still be recommended, but state the boundary explicitly.

- **Comment thread — READ the last few comments of every finalist.** The body never
  admits an issue is dead; the thread does. An issue with 0 PRs and a clean title can
  still be resolved, stale, or deflected. Skip/downgrade on:

  ```bash
  gh api repos/<owner/name>/issues/<number>/comments --paginate \
    --jq '.[] | "@\(.user.login) (\(.created_at[0:10])): \(.body)"'
  ```
  - Reporter/others **root-cause it to upstream or another repo** and say it works
    after a fix (e.g. "this is actually sglang #19335, applied the fix, results fine")
    → likely **already resolved** → check that upstream issue's state; if closed, skip.
  - A **fix/patch already posted in a comment** (gist, diff, "apply this") → the hard
    work is done and the author will probably PR it → low value to duplicate.
  - "**try latest / can't repro on main**" with no follow-up → likely **stale or fixed**
    → re-verify against current `main` before investing.
  - Maintainer **asked for info that never came**, or "**use X instead**" deflection
    → wontfix-ish → skip.
- **Local checkout** (optional): if a repo has a `path` **and it exists on disk**,
  you may grep/read it to judge feasibility more concretely (does the fix touch
  code I understand? how big is the surface?). Use it when an issue is borderline —
  don't crawl it for all. If the path is missing, just skip it; never block on it.

### 3. Judge — the actual product

Decide contributability by weighing these together, NOT by literal
interest-keyword matching:

1. **资源约束** — does it need hardware the user doesn't have (H20 / Blackwell /
   GB200 / multi-node / AMD / NPU …)? The user has: see `resources`. If it needs
   more than they have → not feasible.
2. **可验证性 (verifiability)** — the sharpest gate, often sharper than "can I run
   the model." Can the user close the **fix → prove it works** loop *on their own
   hardware*? A fix they can't verify is nearly worthless: they can't confidently
   submit it and maintainers won't merge an unverifiable patch. Three tiers:
   - **self-verifiable** — reproducible/checkable on the user's box (small model on
     the single Spark, or pure-code / zero-GPU: deps, docs, packaging, a localized
     logic bug provable by a unit test). **Rank these highest.**
   - **partially verifiable** — fix is code-level and reviewable, but full e2e repro
     needs hardware they lack. Acceptable, but **say so explicitly** and note the
     contribution path is "reasoned fix + reporter/maintainer verifies."
   - **not locally verifiable** — only the reporter's rig (e.g. 8×H200 multimodal
     MLA) can confirm. **Down-rank, and label the verification barrier.** Don't bury
     these among normal recommendations. (Real example: #29008 was diagnosable and
     fixable on paper but unverifiable on a single Spark — a poor fit despite being
     "code-level.")
3. **兴趣与技能** — matches rank higher, but interest is not the only gate.
4. **客观事实** — has an open PR (linked or found by reverse search) / is assigned /
   the author said they would fix it / heavily参与 / long stale. An issue is only
   "free" after the linked-PR query, reverse PR search, and author-intent read all
   pass. One of the three passing is not enough.

Rules:

- The recommended list holds only issues the user could **realistically pick up
  now**. 宁缺毋滥 — usually 5–10 is plenty. Each recommendation needs a concrete
  reason, a resource verdict, and a **verification verdict** (self / partial / not
  local); if evidence is thin, say so. **Order recommendations by verifiability
  first** (self-verifiable on top), then priority — a closeable loop beats a
  higher-impact bug the user can't prove fixed.
- Move the rest into a **collapsed skipped summary** — do NOT write full cards for
  them. Bucket each as: `resource` (hardware they lack), `occupied` (open PR /
  assigned, and you see no unique value they'd add), `claimed` (no PR yet, but the
  author stated intent or already has the patch), `resolved` (the thread shows it
  fixed elsewhere / not reproducible / wontfix), or `unclear` (too little info).
- **Serendipity (required): include 1–2 picks deliberately OUTSIDE the user's
  interests** — something you find genuinely interesting or worth doing and that is
  resource-feasible, to break them out of their bubble. Because of this, do not
  pre-filter candidates by interest; judge the whole pool.

### 4. Write the report

Write Markdown to `<output_dir>/reports/YYYY-MM-DD.md` (expand `output_dir`,
`mkdir -p` the `reports/` dir). Rerunning the same day overwrites that day's file.
Reports live here, NOT in the user's Obsidian vault — a triage sweep is inbox-grade,
not knowledge. Issues the user actually decides to work on graduate into the vault
by hand. Write the report 以中文为主.

Report shape:

```markdown
# osmind 贡献雷达 · YYYY-MM-DD

推荐 N 条（首次出现 F 条）· serendipity M 条 · 跳过 K 条 · task pack P 个

## 推荐贡献

### [owner/name#123](https://github.com/owner/name/issues/123) — <title>
- 优先级: high|medium|low
- 理由: ...
- 资源: ...
- 验证: self|partial|not-local — 怎么验、能不能在单卡 Spark 闭环
- pack: `packs/<slug>-123.md`（未出 pack 的写 —，并说明原因）

（重复每一条；先按可验证性 self→partial→not-local，再按优先级从高到低）

## 跳出兴趣（serendipity）

### [owner/name#456](...) — <title>
- 为什么值得一看（兴趣点之外）: ...
- 资源: ...

## 已跳过（K 条）
- 已有 OPEN PR / 已指派: #a→PR #x, #b, ...   （PR 号必须写出来）
- 作者已认领（无 PR）: #c —「原话」, ...
- 线程内已解决: #d, ...
- 资源不可行: #e, #f, ...
- 信息不足 / 未核验可行性: #g, ...

## 备注
- （任何 fetch 失败的仓库写在这里）
- （有推荐但缺 work_path、因而没有 queue 行的仓库也写在这里）
```

### 5. Emit task packs + a batch queue

The report is for the human; the pack is for the machine. Without this step every
recommendation has to be hand-rewritten before it can be run, which is where the
funnel actually leaks.

Write one pack per recommendation whose verification verdict is **self** (packs for
`partial` only if the user asks — an agent cannot close the loop on them). Path:
`<output_dir>/packs/<slug>-<number>.md` (`mkdir -p` it), where `<slug>` is the repo's
short name (`litellm`, `sglang`, `slime`, `omni`). Rerunning the same day overwrites.

Pack shape — plain text, no YAML, consumed by a coding agent as its whole brief:

```
Issue: owner/name#123 — <title>
URL: https://github.com/owner/name/issues/123

Symptom: what the user observes, concretely. Include the failing call/config.

Root cause: only what the issue, linked code, or your own reading of the local
checkout actually establishes — cite where it came from. If it is NOT established,
write "Not established in the issue; diagnose before fixing." Never invent one.

Expected: the observable behavior after a correct fix.

Fix scope: the smallest change that fixes it, named down to file/function where
known. Then the guards, explicitly:
  - Do NOT special-case the test input or hardcode the expected value.
  - Do NOT weaken, skip, or delete existing tests.
  - Do NOT widen the change beyond this issue.

Smallest reproducing test: how to turn the repro into one test in the repo's
existing test tree, offline (no network, no API key, no model download unless the
resource verdict says otherwise).
  - RED (current code): the exact assertion that fails today, and why it fails.
  - Guard: an assertion covering the neighbouring behavior that must keep working.
Difficulty: easy|medium|hard. One line on why.

ENVIRONMENT (already prepared — do NOT rebuild it): <the repo's env_note verbatim;
if the profile has none, write "No prepared runtime recorded — confirm with the
user before installing anything.">
```

The RED line is the load-bearing part: a pack whose failing assertion you cannot
state concretely is not ready — drop it back to a recommendation-only entry and say
why in the report.

Then append one queue line per pack whose repo has a `work_path`, to
`<output_dir>/queue-YYYY-MM-DD.jsonl` (one JSON object per line, no trailing comma):

```json
{"repo": "/abs/path/to/work_path", "issue_no": 123, "difficulty": "easy", "base": "main", "pack_path": "packs/<slug>-123.md"}
```

`repo` must be the absolute `work_path` (never the read-only `path`), `base` the
profile's `base` for that repo. `pack_path` is resolved **relative to the queue
file's own directory** by the runner, so keep the queue and `packs/` side by side
under `output_dir` (or write an absolute path).

### 6. Append to the ledger

`<output_dir>/ledger.jsonl`, append-only, one JSON object per line. This is the
only thing that survives a run, and it exists because without it the radar cannot
answer "did I already look at this?" — two consecutive runs re-judged and re-skipped
144 and 146 issues with no way to tell which were new.

**Write it; do not judge from it.** Reading past verdicts to shortcut this run's
judgement is exactly what statelessness protects against: issues change — a repro
gets added, a maintainer answers, a dependency lands — and a cached "unclear" would
freeze that. The single permitted read is the *existence* check below, which asks
"has this number appeared before", never "what did I decide".

One line per recommendation and per serendipity pick:

```json
{"date":"YYYY-MM-DD","issue":"owner/name#123","verdict":"recommended","verification":"self","pack":"packs/litellm-35531.md","first_seen":true}
```

`verdict` is `recommended` or `serendipity`; `verification` is self/partial/not-local;
`pack` is the path or null. Plus **one** aggregate line per run for everything skipped
— never one line per skipped issue:

```json
{"date":"YYYY-MM-DD","run":"summary","reviewed":150,"recommended":4,"serendipity":2,"skipped":{"occupied":26,"claimed":5,"resolved":1,"resource":52,"unclear":60},"repos_skipped":["THUDM/slime"]}
```

The permitted read: before writing, grep the ledger for each recommended issue's
number to set `first_seen`, and report the count ("本轮 N 条推荐中 M 条首次出现").
That is the answer to the question the user actually asks.

Downstream work appends its own lines later — by hand or by another tool — so the
chain from a pick to a verified trajectory is reconstructable:

```json
{"date":"YYYY-MM-DD","issue":"BerriAI/litellm#35590","event":"agentcap","session":"codex-litellm-35590-…","replay":"red_green","verified":true}
```

Never rewrite or delete existing lines; a wrong earlier line is corrected by a new
line, not by editing history.

### 7. Notify + report back

Fire a desktop notification, best-effort — a missing notifier must never fail the
run or change the report:

```bash
SUMMARY="推荐 N 条，serendipity M 条，pack P 个"
if command -v notify-send >/dev/null 2>&1; then
  notify-send "osmind 贡献雷达 · YYYY-MM-DD" "$SUMMARY"
elif command -v osascript >/dev/null 2>&1; then
  osascript -e "display notification \"$SUMMARY\" with title \"osmind 贡献雷达\" subtitle \"YYYY-MM-DD\""
fi
```

(Linux hosts have `notify-send`; macOS has `osascript`. If neither exists, skip it
silently and note it in the run summary, not in the report.)

Finally print to the user: the report path, the pack paths, the queue path, and the
one-line summary.

## Scheduling (push)

This skill is pull (the user invokes it). To make it push on a schedule, run it
headless:

```bash
claude -p "run the osmind skill" --allowedTools "Bash,Read,Write"
```

Wire that to a **systemd user timer** on Linux (`systemctl --user enable --now
osmind.timer`; needs `loginctl enable-linger` to fire while logged out) or a
**launchd** job on macOS. Set it up only if the user asks — they may prefer on demand.

## Don't

- Don't invent issues — only ever recommend ones returned by `gh`.
- Don't call an issue free on the linked-PR query alone. Empty means "nothing linked",
  not "nobody is on it" — a PR referencing the issue by bare URL links nothing. Pair it
  with the reverse PR search and an author-intent read, every time.
- Don't invent a root cause, a repro command, or a RED assertion in a pack. Every
  pack claim is either grounded in the issue/code or explicitly marked unestablished.
- Don't write a pack that tells the agent to make a test pass by special-casing it,
  and don't let a pack license weakening existing tests.
- Don't put a read-only `path` in a queue line's `repo` — that's `work_path`'s job.
- Don't write to the Obsidian vault.
- Don't store state between runs beyond the append-only ledger, and never read the
  ledger's verdicts — only whether an issue number has appeared before. Packs, queues
  and reports are outputs, not state: never read last run's packs to bias this run.
- Don't rewrite or delete ledger lines. Correct a wrong line by appending a new one.
- Don't dump a long low-value list; the skipped summary is where the noise goes.
