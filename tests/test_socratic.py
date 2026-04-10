import pytest
from unittest.mock import MagicMock
from osmind.engine.socratic import SocraticEngine
from osmind.github.models import GHPR, PRFile


@pytest.fixture
def engine():
    mock_llm = MagicMock()
    mock_llm.chat.return_value = "这个 PR 同时改了 model/ 和 engine/，你觉得为什么模型适配需要动 engine 层？"
    return SocraticEngine(llm=mock_llm)


def test_generate_question_for_pr(engine):
    pr = GHPR(
        number=99, title="feat: add Qwen3MoE",
        body="Adds MoE support", url="u", repo="r",
        files=[
            PRFile("model/qwen3.py", "@@ +1 @@\n+class Qwen3MoE: pass"),
            PRFile("engine/batch.py", "@@ +5 @@\n+def schedule_moe(): pass"),
        ],
    )
    q = engine.first_question(pr)
    assert isinstance(q, str)
    assert len(q) > 10


def test_followup_uses_conversation_history(engine):
    engine._llm.chat.return_value = "你提到了解耦，那 batching 在哪一层决定？"
    history = [
        {"role": "assistant", "content": "为什么 engine 层需要改？"},
        {"role": "user", "content": "因为 MoE 需要动态路由"},
    ]
    q = engine.followup(history)
    assert "batching" in q or len(q) > 5
