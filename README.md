# osmind

**osmind** is a terminal UI for developers who want to contribute to open source but don't know where to start.

It watches GitHub repositories you care about, recommends issues that match your skills, guides you through reading PRs with Socratic questions, and accumulates your understanding as notes in your Obsidian vault — so knowledge compounds over time instead of evaporating.

```
┌─ osmind ─────────────────────────────────────────────────────┐
│ [Discover]  [Learn]  [Review]                      q: Quit   │
├──────────────────────────────────────────────────────────────┤
│ Repo: sgl-project/sglang              Filter: all  ▼         │
│                                                              │
│  ★★★  #2341  Add Qwen3MoE model support            [feat]   │
│  ★★☆  #2298  Tokenizer memory leak on long seqs    [bug]    │
│  ★☆☆  #2187  Refactor engine batch scheduler       [refac]  │
│                                                              │
│  推荐理由: 涉及模型适配，你有 SGLang PR 经验，改动主要在     │
│  model/ 目录，预估 200 行                                    │
└──────────────────────────────────────────────────────────────┘
```

## Why

Most large open source projects are hard to enter — the roadmap is dense, every issue assumes context you don't have yet, and it's unclear which PRs are worth reading to build that context.

osmind solves this by:
- **Matching issues to your profile** — it knows your skills and interests, scores every open issue, and surfaces the ones you're most likely to be able to work on
- **Teaching through PRs** — instead of summarizing PRs for you, it asks questions that make you articulate what you understood, then saves your answers as notes
- **Building a knowledge base** — notes accumulate in your Obsidian vault, linked to repos and modules; over time you build a real mental model of the codebase

## How it works

osmind has three modes:

### Discover

Fetches open issues from your watched repos. Each issue is scored against your `profile.yaml` (interests, skills, available compute) by a local or remote LLM. Results are sorted by match score with a one-sentence explanation of why each issue fits you.

Press `c` or `x` on any issue to launch **Claude Code** or **Codex** directly with the issue context pre-loaded. You can read how the agent approaches the fix, even if you don't write the code yourself — that's learning too.

### Learn

Enter a PR number. osmind fetches the diff and asks you one Socratic question at a time:

> "This PR touches both `model/` and `engine/batch.py`. Why do you think a model adapter change would need to touch the batching layer?"

You answer in your own words. osmind asks a follow-up. When you're satisfied, `Ctrl+S` saves the conversation as a structured note in your Obsidian vault — tagged by repo, module, and PR number.

### Review

osmind reads your saved notes and finds gaps — questions you marked as uncertain, or modules you've seen mentioned but never explained. It asks you about them, and your answers get appended back to the original note.

## Installation

Requires Python 3.11+.

```bash
git clone https://github.com/yourname/osmind
cd osmind
pip install -e .
```

## Configuration

```bash
cp profile.yaml.example profile.yaml
```

Edit `profile.yaml`:

```yaml
interests:
  - RL post-training
  - SGLang inference optimization

skills:
  - Python
  - distributed training

resources:
  gpus: "4x RTX 4090"
  time: part-time

watching:
  - repo: THUDM/slime
  - repo: sgl-project/sglang

notes_vault: ~/workspace/Note  # your Obsidian vault path

llm:
  base_url: http://localhost:30000/v1  # SGLang local endpoint, or any OpenAI-compatible API
  model: Qwen3.5-27B
  api_key: placeholder

external_agents:
  claude_code: claude
  codex: codex
```

Set your GitHub token:

```bash
export GITHUB_TOKEN=ghp_...
```

Run:

```bash
osmind
```

## LLM backend

osmind uses any **OpenAI-compatible** API for issue ranking and Socratic questions. Point `llm.base_url` at whatever you're running:

| Backend | `base_url` |
|---------|-----------|
| SGLang (local) | `http://localhost:30000/v1` |
| OpenAI | `https://api.openai.com/v1` |
| Ollama | `http://localhost:11434/v1` |
| Any other compatible server | your endpoint |

For the ranking and Socratic use case, a 7B–27B local model is sufficient.

## Keybindings

| Key | Action |
|-----|--------|
| `d` | Discover tab |
| `l` | Learn tab |
| `r` | Review tab |
| `f` | Fetch issues (Discover) |
| `c` | Launch Claude Code on selected issue |
| `x` | Launch Codex on selected issue |
| `Ctrl+S` | Save note (Learn) |
| `q` | Quit |

## Tech stack

- [Textual](https://github.com/Textualize/textual) — terminal UI framework
- [PyGithub](https://github.com/PyGithub/PyGithub) — GitHub API
- [openai](https://github.com/openai/openai-python) — LLM client (OpenAI-compatible)
- Notes stored as plain Markdown with YAML frontmatter — no new tools required if you already use Obsidian
