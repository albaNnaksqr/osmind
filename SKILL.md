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
- 验证: self|partial|not-local — 怎么验、能不能在单卡 Spark 闭环

（重复每一条；先按可验证性 self→partial→not-local，再按优先级从高到低）

## 跳出兴趣（serendipity）

### [owner/name#456](...) — <title>
- 为什么值得一看（兴趣点之外）: ...
- 资源: ...

## 已跳过（K 条）
- 已有 OPEN PR / 已指派: #a→PR #x, #b, ...
- 作者已认领（无 PR）: #c —「支持这一判断的原话」, ...
- 线程内已解决: #d, ...
- 资源不可行: #e, #f, ...
- 信息不足 / 未核验可行性: #g, ...

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
- Don't call an issue free from the linked-PR query alone. Empty means "nothing
  linked", not "nobody is working on it". Pair it with the reverse PR search and
  an author-intent read for every finalist.
- Don't write to the Obsidian vault.
- Don't store state between runs — there is no memory, by design.
- Don't dump a long low-value list; the skipped summary is where the noise goes.
