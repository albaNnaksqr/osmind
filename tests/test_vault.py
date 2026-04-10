import pytest
from pathlib import Path
from osmind.notes.vault import NotesVault, Note


@pytest.fixture
def vault(tmp_path):
    return NotesVault(tmp_path)


def test_save_and_load_note(vault):
    note = Note(
        repo="sgl-project/sglang",
        pr_number=99,
        pr_title="feat: add Qwen3MoE",
        modules=["model", "engine/batch"],
        tags=["model-adaptation"],
        content="SGLang decouples tokenizer from engine.",
        pending_questions=["Where is batching decided?"],
    )
    vault.save(note)

    loaded = vault.load_for_pr("sgl-project/sglang", 99)
    assert loaded is not None
    assert loaded.pr_number == 99
    assert loaded.content == "SGLang decouples tokenizer from engine."
    assert loaded.pending_questions == ["Where is batching decided?"]


def test_list_pending_questions(vault):
    n1 = Note(repo="THUDM/slime", pr_number=1, pr_title="fix: training",
               modules=[], tags=[], content="learned X",
               pending_questions=["What is Y?"])
    n2 = Note(repo="sgl-project/sglang", pr_number=2, pr_title="feat: Z",
               modules=[], tags=[], content="learned A",
               pending_questions=[])
    vault.save(n1)
    vault.save(n2)

    pending = vault.list_pending_questions()
    assert len(pending) == 1
    assert pending[0][0].pr_number == 1
    assert pending[0][1] == "What is Y?"


def test_append_answer(vault):
    note = Note(repo="sgl-project/sglang", pr_number=5, pr_title="fix: mem",
                modules=[], tags=[], content="initial",
                pending_questions=["How does batching work?"])
    vault.save(note)

    vault.append_answer("sgl-project/sglang", 5, "How does batching work?", "It works via scheduler.")
    loaded = vault.load_for_pr("sgl-project/sglang", 5)
    assert "How does batching work?" not in loaded.pending_questions
    assert "It works via scheduler." in loaded.content
