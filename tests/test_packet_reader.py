from __future__ import annotations


def test_packet_reader_extracts_title_and_sections():
    from osmind.tui.packet_reader import packet_outline, packet_section_markdown

    markdown = """---
type: osmind-contribution-packet
---

# Issue #42: Tokenizer leak

## What This Is

Issue summary.

## First 10 Minutes

1. Search for `tokenizer`.

## Validation Path

- Run a focused regression test.
"""

    outline = packet_outline(markdown)

    assert [section.title for section in outline] == [
        "Overview",
        "What This Is",
        "First 10 Minutes",
        "Validation Path",
    ]
    assert packet_section_markdown(markdown, 0).startswith("# Issue #42: Tokenizer leak")
    assert packet_section_markdown(markdown, 2) == "## First 10 Minutes\n\n1. Search for `tokenizer`."
