from osmind.services.recommend import build_user_prompt, _normalize


def make_candidate(repo="sgl-project/sglang", number=1, title="Fix cache", **signal_overrides):
    signals = {
        "number": number,
        "labels": ["bug"],
        "assignees": [],
        "comment_count": 3,
        "linked_open_prs": [],
        "updated_at": "2026-06-10T00:00:00",
    }
    signals.update(signal_overrides)
    return {
        "repo": repo,
        "number": number,
        "title": title,
        "body": "some body text",
        "signals": signals,
    }


def test_prompt_includes_signals_and_serendipity_instruction():
    profile = {"interests": ["sglang"], "skills": ["python"], "resources": {"gpus": "1 x Spark"}}
    candidates = [make_candidate(linked_open_prs=[42], assignees=["bob"])]
    prompt = build_user_prompt(profile, candidates)

    assert "open_pr=yes #42" in prompt
    assert "assignees=bob" in prompt
    assert "1 x Spark" in prompt
    assert "未按兴趣预筛" in prompt  # candidate set is not interest-filtered


def test_normalize_drops_hallucinated_issues():
    candidates = [make_candidate(number=1)]
    raw = {
        "summary": "ok",
        "recommendations": [
            {"repo": "sgl-project/sglang", "number": 1, "priority": "HIGH", "reason": "r", "serendipity": False},
            {"repo": "sgl-project/sglang", "number": 999, "priority": "high", "reason": "fake"},
        ],
    }
    result = _normalize(raw, candidates)
    assert len(result["recommendations"]) == 1
    assert result["recommendations"][0]["number"] == 1
    assert result["recommendations"][0]["priority"] == "high"  # lowercased


def test_normalize_counts_serendipity():
    candidates = [make_candidate(number=1), make_candidate(number=2)]
    raw = {
        "recommendations": [
            {"repo": "sgl-project/sglang", "number": 1, "serendipity": False},
            {"repo": "sgl-project/sglang", "number": 2, "serendipity": True},
        ]
    }
    result = _normalize(raw, candidates)
    assert result["serendipity_count"] == 1


def test_normalize_categorizes_skipped():
    candidates = [make_candidate(number=n) for n in (1, 2, 3, 4)]
    raw = {
        "recommendations": [{"repo": "sgl-project/sglang", "number": 1, "priority": "high"}],
        "skipped": [
            {"repo": "sgl-project/sglang", "number": 2, "category": "resource"},
            {"repo": "sgl-project/sglang", "number": 3, "category": "occupied"},
            {"repo": "sgl-project/sglang", "number": 4, "category": "bogus"},  # → unclear
        ],
    }
    result = _normalize(raw, candidates)
    assert len(result["recommendations"]) == 1
    assert result["skipped"]["resource"] == [{"repo": "sgl-project/sglang", "number": 2}]
    assert result["skipped"]["occupied"] == [{"repo": "sgl-project/sglang", "number": 3}]
    assert result["skipped"]["unclear"] == [{"repo": "sgl-project/sglang", "number": 4}]
    assert result["skipped_count"] == 3


def test_normalize_skips_item_already_recommended():
    candidates = [make_candidate(number=1)]
    raw = {
        "recommendations": [{"repo": "sgl-project/sglang", "number": 1, "priority": "high"}],
        "skipped": [{"repo": "sgl-project/sglang", "number": 1, "category": "resource"}],
    }
    result = _normalize(raw, candidates)
    assert result["skipped_count"] == 0  # already in recommendations, not double-counted
