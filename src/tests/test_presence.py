import pytest

import reminders
from assistant import presence
from indexing.proposals import Proposal, ProposedChange
from resume import store
from resume.schema import Bilingual, Conflict, Evidence, PersonalInfo, Resume
from visualizer import state


def make_resume(**kwargs) -> Resume:
    return Resume(personal_info=PersonalInfo(full_name="Fulano", phone="A"), summary=Bilingual(pt="Resumo."), **kwargs)


def _evidence() -> list[Evidence]:
    return [Evidence(source_path="/x.docx", source_type="docx", read_at="2026-01-01T00:00:00Z")]


def _conflict(status: str) -> Conflict:
    return Conflict(
        id=f"conflict-{status}",
        field_path="personal_info.phone",
        existing_value="A",
        proposed_value="B",
        sources=_evidence(),
        detected_at="2026-01-01T00:00:00Z",
        status=status,
    )


@pytest.fixture(autouse=True)
def isolated(tmp_path, monkeypatch):
    # Every source points at tmp_path -- never the real src/data/.
    import config

    monkeypatch.setattr(store, "RESUME_PATH", tmp_path / "resume.json")
    monkeypatch.setattr(store, "BACKUPS_DIR", tmp_path / "backups")
    monkeypatch.setattr(config, "PROPOSALS_DIR", tmp_path / "proposals")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    monkeypatch.delenv(presence.ENABLED_ENV_VAR, raising=False)
    monkeypatch.setattr(state, "_subscribers", [])
    monkeypatch.setattr(state, "_current_presence", None)
    store.save(make_resume())
    return tmp_path


def _write_proposal(tmp_path, name: str, n_changes: int) -> None:
    proposals_dir = tmp_path / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    changes = [
        ProposedChange(
            kind="update_field",
            field_path="personal_info.phone",
            proposed_value=f"B{i}",
            existing_value="A",
            evidence=_evidence(),
        )
        for i in range(n_changes)
    ]
    proposal = Proposal(created_at="2026-01-01T00:00:00Z", source_files=["/x.docx"], changes=changes)
    (proposals_dir / name).write_text(proposal.model_dump_json(), encoding="utf-8")


def test_nothing_pending_gives_no_items():
    assert presence.build_presence_items() == []
    assert presence.format_text([]) == "Nada pendente."


def test_pending_proposal_changes_are_counted_across_files(isolated):
    _write_proposal(isolated, "proposal_20260101T000000Z.json", n_changes=2)
    _write_proposal(isolated, "proposal_20260102T000000Z.json", n_changes=1)

    items = presence.build_presence_items()

    assert len(items) == 1
    assert items[0].why.startswith("3 mudanças aguardando")
    assert items[0].action == "python src/cli.py review-proposals"


def test_singular_wording_for_one_change(isolated):
    _write_proposal(isolated, "proposal_20260101T000000Z.json", n_changes=1)

    (item,) = presence.build_presence_items()

    assert item.why.startswith("1 mudança aguardando")


def test_unreadable_proposal_is_reported_not_guessed(isolated):
    proposals_dir = isolated / "proposals"
    proposals_dir.mkdir(parents=True, exist_ok=True)
    (proposals_dir / "proposal_20260101T000000Z.json").write_text("not json", encoding="utf-8")

    (item,) = presence.build_presence_items()

    assert item.why == "1 proposta não pôde ser lida."
    assert "mudança" not in item.why


def test_only_open_conflicts_count():
    resume = make_resume()
    resume.conflicts.extend([_conflict("open"), _conflict("resolved_proposed")])
    store.save(resume)

    (item,) = presence.build_presence_items()

    assert item.source == "Currículo · conflitos entre fontes"
    assert item.why.startswith("1 conflito em aberto")


def test_reminders_are_counted():
    reminders.add_reminder("ligar para o RH")
    reminders.add_reminder("enviar portfólio")

    (item,) = presence.build_presence_items()

    assert item.source == "Lembretes"
    assert item.why == "2 lembretes anotados."
    assert "quais são meus lembretes" in item.action


def test_a_failing_source_is_skipped_without_hiding_the_others(isolated):
    # Missing résumé makes store.load() raise -- the conflict source must
    # contribute nothing (no guessed count), and the rest still works.
    (isolated / "resume.json").unlink()
    reminders.add_reminder("x")

    items = presence.build_presence_items()

    assert [i.source for i in items] == ["Lembretes"]


def test_payload_and_text_keep_the_source_why_action_format():
    items = [presence.PresenceItem(source="Fonte", why="Porque sim.", action="faça X")]

    assert presence.to_payload(items) == {
        "title": "Sugestões",
        "items": [{"source": "Fonte", "why": "Porque sim.", "action": "faça X"}],
    }
    assert presence.format_text(items) == "- Fonte: Porque sim.\n  → faça X"


def test_disabled_by_default_publishes_nothing():
    reminders.add_reminder("x")

    assert presence.is_enabled() is False
    assert presence.publish_if_enabled() is False
    assert state.current_presence() is None


@pytest.mark.parametrize("value", ["false", "0", "", "yes"])
def test_only_literal_true_enables(monkeypatch, value):
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, value)
    assert presence.is_enabled() is False


def test_enabled_publishes_the_card(monkeypatch):
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, "TRUE")
    reminders.add_reminder("x")

    assert presence.publish_if_enabled() is True

    event = state.current_presence()
    assert event.kind == state.PRESENCE_KIND
    assert event.payload["items"][0]["source"] == "Lembretes"


def test_enabled_with_nothing_pending_clears_a_stale_card(monkeypatch):
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, "true")
    state.publish_presence({"title": "Sugestões", "items": [{"source": "velho", "why": "", "action": ""}]})

    assert presence.publish_if_enabled() is False
    assert state.current_presence() is None


def test_presence_never_touches_the_network(monkeypatch):
    import socket

    def _no_network(*_args, **_kwargs):
        raise AssertionError("presence must not open a network connection")

    monkeypatch.setattr(socket, "create_connection", _no_network)
    monkeypatch.setattr(socket.socket, "connect", _no_network)
    monkeypatch.setenv(presence.ENABLED_ENV_VAR, "true")
    reminders.add_reminder("x")

    assert presence.publish_if_enabled() is True
