"""Proactive "presence" card for the HUD -- Noah's own, local-first take
on the routine idea from xAI's Grok Bot (public page only, clean-room;
see docs/ADR-0001-presenca-local-first.md).

Each suggestion is a PresenceItem in the format fonte -> por que importa ->
o que fazer, and the "o que fazer" is only ever a suggestion (a command or a
phrase to say) -- nothing here executes it.

Same posture as assistant/briefing.py: every fact is counted from files
already on disk, never produced by the LLM, so a count can't be invented.
Unlike briefing.py there's no news headline here -- presence never touches
the network, and there's no cloud fallback of any kind. A source that fails
to load is skipped (fail closed: no guessed number), and when nothing is
pending the item list is simply empty -- the HUD shows nothing at all.

Off by default in the HUD: publish_if_enabled() only does anything with
NOAH_PRESENCE_ENABLED=true. `python src/cli.py presenca` is an explicit
read and always works.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass

logger = logging.getLogger(__name__)

ENABLED_ENV_VAR = "NOAH_PRESENCE_ENABLED"


@dataclass(frozen=True)
class PresenceItem:
    source: str
    why: str
    action: str


def is_enabled() -> bool:
    # Live lookup (not a module-level constant) -- monkeypatch.setenv works in tests.
    return os.environ.get(ENABLED_ENV_VAR, "false").strip().lower() == "true"


def _plural(n: int, singular: str, plural: str) -> str:
    return f"{n} {singular if n == 1 else plural}"


def _proposal_items() -> list[PresenceItem]:
    from indexing import review

    pending = review.pending_proposal_paths()
    total_changes = 0
    unreadable = 0
    for p in pending:
        try:
            total_changes += len(review.load_proposal(p).changes)
        except Exception:
            unreadable += 1

    items: list[PresenceItem] = []
    if total_changes:
        items.append(
            PresenceItem(
                source="Currículo · propostas do indexador",
                why=_plural(total_changes, "mudança aguardando", "mudanças aguardando")
                + " sua revisão; nada entra no currículo sem você aceitar.",
                action="python src/cli.py review-proposals",
            )
        )
    if unreadable:
        items.append(
            PresenceItem(
                source="Currículo · propostas do indexador",
                why=_plural(unreadable, "proposta não pôde ser lida", "propostas não puderam ser lidas")
                + ".",
                action="python src/cli.py review-proposals (mostra o erro real)",
            )
        )
    return items


def _conflict_items() -> list[PresenceItem]:
    from resume import store

    open_conflicts = [c for c in store.load().conflicts if c.status == "open"]
    if not open_conflicts:
        return []
    return [
        PresenceItem(
            source="Currículo · conflitos entre fontes",
            why=_plural(len(open_conflicts), "conflito em aberto", "conflitos em aberto")
            + "; duas fontes discordam e nenhuma foi sobrescrita.",
            action='Revise "conflicts" em src/data/resume.json e decida qual fonte vale.',
        )
    ]


def _reminder_items() -> list[PresenceItem]:
    import reminders

    count = len(reminders.list_reminders())
    if not count:
        return []
    return [
        PresenceItem(
            source="Lembretes",
            why=_plural(count, "lembrete anotado", "lembretes anotados") + ".",
            action='Diga: "Noah, quais são meus lembretes?"',
        )
    ]


_SOURCES = (_proposal_items, _conflict_items, _reminder_items)


def build_presence_items() -> list[PresenceItem]:
    items: list[PresenceItem] = []
    for source in _SOURCES:
        try:
            items.extend(source())
        except Exception:
            # Fail closed: an unreadable source contributes nothing rather
            # than a guessed count, and never takes the other sources down.
            logger.warning("presença: fonte %s indisponível", source.__name__, exc_info=True)
    return items


def to_payload(items: list[PresenceItem]) -> dict:
    return {"title": "Sugestões", "items": [asdict(i) for i in items]}


def format_text(items: list[PresenceItem]) -> str:
    if not items:
        return "Nada pendente."
    return "\n".join(f"- {i.source}: {i.why}\n  → {i.action}" for i in items)


def publish_if_enabled() -> bool:
    """Publishes the card to the HUD when enabled and there's something to
    show; with nothing pending, clears any stale card instead. Returns
    whether a non-empty card was published. Best-effort by design: a
    failure here must never break opening the HUD."""
    if not is_enabled():
        return False
    from visualizer import state

    items = build_presence_items()
    if not items:
        state.clear_presence()
        return False
    state.publish_presence(to_payload(items))
    return True
