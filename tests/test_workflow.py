from __future__ import annotations


def test_start_work_summary_extracts_execution_sections():
    from osmind.tui.workflow import format_start_work_from_packet

    markdown = """---
type: osmind-contribution-packet
source_type: issue
repo: o/r
number: 42
title: Tokenizer leak
url: https://github.com/o/r/issues/42
decision: continue
---

# Issue #42: Tokenizer leak

## Why It May Fit You

推荐理由: current GPU is enough for a repro.

## Continue Or Stop Criteria

### Continue
- Continue if a small test can reproduce the leak.

### Stop
- Stop if no validation path appears.

## First 10 Minutes

1. Restate the report.
2. Search for `tokenizer`.

## Files And Symbols To Inspect

- `tokenizer`
- `cache`

## Validation Path

- Run the smallest tokenizer regression test.

## Agent Exploration Prompt

Help me investigate issue #42.
"""

    summary = format_start_work_from_packet(markdown, {"gpus": "4x RTX 4090"})

    assert "Start Work" in summary
    assert "Issue #42: Tokenizer leak" in summary
    assert "Decision: continue" in summary
    assert "Resources: gpus: 4x RTX 4090" in summary
    assert "First 10 Minutes" in summary
    assert "Search for `tokenizer`" in summary
    assert "Files And Symbols To Inspect" in summary
    assert "Validation Path" in summary
    assert "### Continue" not in summary
    assert "[bold]Continue[/bold]" in summary
    assert "Stop if no validation path appears." in summary
    assert "Agent Exploration Prompt" in summary


def test_start_work_summary_warns_when_decision_is_defer():
    from osmind.tui.workflow import format_start_work_from_packet

    markdown = """---
type: osmind-contribution-packet
source_type: issue
repo: o/r
number: 7
title: DeepSeek V4Pro reproduction
url: https://github.com/o/r/issues/7
decision: defer
---

# Issue #7: DeepSeek V4Pro reproduction

## Why It May Fit You

资源不足。
"""

    summary = format_start_work_from_packet(markdown, {"gpus": "1x RTX 4090"})

    assert "Do not start yet" in summary
    assert "Decision: defer" in summary
    assert "Resources: gpus: 1x RTX 4090" in summary


def test_start_work_summary_uses_new_issue_brief_section_titles():
    from osmind.tui.workflow import format_start_work_from_packet

    markdown = """---
type: osmind-contribution-packet
source_type: issue
repo: o/r
number: 42
title: Tokenizer leak
url: https://github.com/o/r/issues/42
decision: continue
---

# Issue #42: Tokenizer leak

## Why It May Fit You

推荐理由: current GPU is enough for a repro.

## First 30 Minutes

1. Restate the report.
2. Search for `tokenizer`.

## Files And Symbols To Inspect

- `tokenizer`

## Validation Path

- Run the smallest tokenizer regression test.

## Agent Prompt

请先对 Issue #42 进行结构化研读。
"""

    summary = format_start_work_from_packet(markdown, {"gpus": "4x RTX 4090"})

    assert "First 30 Minutes" in summary
    assert "Agent Prompt" in summary
    assert "Restate the report." in summary
    assert "Search for `tokenizer`" in summary
    assert "请先对 Issue #42 进行结构化研读。" in summary
    assert "First 10 Minutes" not in summary
    assert "Open the packet and identify the first concrete read or reproduction step." not in summary


def test_start_work_summary_formats_markdown_headings_for_tui():
    from osmind.tui.workflow import format_start_work_from_packet

    markdown = """---
type: osmind-contribution-packet
source_type: issue
repo: o/r
number: 42
title: Tool call parser
url: https://github.com/o/r/issues/42
decision: continue
---

# Issue #42: Tool call parser

## Repo Grounding

### Scope
- Repo: `o/r`

### Highest-Signal Matches
- `src/parser.py:10` matched `tool_calls`: value contains [nested] markers

## First 30 Minutes

1. Read `src/parser.py`.

## Files And Symbols To Inspect

- `src/parser.py`

## Validation Path

- Add a parser test.

## Agent Prompt

Investigate the parser.
"""

    summary = format_start_work_from_packet(markdown)

    assert "### Scope" not in summary
    assert "[bold]Scope[/bold]" in summary
    assert "value contains \\[nested] markers" in summary
