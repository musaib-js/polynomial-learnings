"""Judge prompt construction (see SDD §6).

Builds the single prompt that carries both of the SDD's judgements — novelty
(same / contradicts / refines an existing learning) and worth-keeping
(generalisable, non-trivial, safe) — from a conversation snapshot and the
learnings retrieved as its neighbours.

Deliberately separate from ``LearningManager.format_for_prompt``, which
renders learnings for an *agent's* system prompt (no ids, human-readable
only). This renderer must expose each neighbour's ``id`` so the Judge can
return a real ``related_learning_id``.
"""

from __future__ import annotations

from .models import Learning, Message

_INSTRUCTIONS = """\
You are curating a durable memory store for an AI agent. Given a recent \
conversation and any related learnings already stored, decide what to do.

Two judgements, in order:

1. Novelty — if any "Existing learnings" below are closely related to what \
this conversation reveals, decide whether the conversation:
   - restates the SAME lesson as one of them (verdict "same", set \
related_learning_id to its id, no new learning needed)
   - CONTRADICTS one of them (verdict "contradict", set related_learning_id \
to its id, and generate the replacement learning)
   - REFINES one of them with more detail or a correction (verdict "refine", \
set related_learning_id to its id, and generate the merged learning)
   If none apply, fall through to worth-keeping.

2. Worth-keeping — if there is no close match, decide whether this \
conversation contains a durable, generalisable lesson worth remembering \
(verdict "new", generate the learning) or whether it is trivial, a one-off \
mistake, or unsafe to retain (verdict "reject", give a brief reason).

When you generate a learning, you also decide its scope: "personal" if it \
only applies to this specific user/entity, or "global" if it is true for \
every user of this agent.
"""


def _render_neighbours(neighbours: list[Learning]) -> str:
    if not neighbours:
        return "Existing learnings: none found.\n"
    lines = ["Existing learnings (closest matches first):"]
    for learning in neighbours:
        lines.append(
            f"- id={learning.id} scope={learning.scope.value} "
            f"context={learning.context!r} content={learning.content!r}"
        )
    return "\n".join(lines) + "\n"


def _render_conversation(messages: list[Message]) -> str:
    lines = ["Conversation:"]
    for message in messages:
        lines.append(f"{message.role}: {message.content}")
    return "\n".join(lines) + "\n"


def build_judge_prompt(messages: list[Message], neighbours: list[Learning]) -> str:
    """Build the full Judge prompt for one persist attempt.

    ``neighbours`` should be the learnings retrieved for this conversation
    (e.g. via ``LearningManager.retrieve_for_conversation``), most relevant
    first. An empty list is valid — it means no related learning exists, so
    the Judge can only answer "new" or "reject".
    """
    return (
        _INSTRUCTIONS
        + "\n"
        + _render_conversation(messages)
        + "\n"
        + _render_neighbours(neighbours)
    )
