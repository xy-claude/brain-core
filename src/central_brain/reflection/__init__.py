"""Reflection capability: end-of-session context gathering + synthesis.

Cost-aware design (see project_central_brain memory):
    * ``gather_session_context`` assembles structured data — the library
      never calls an LLM.
    * ``template_summary`` produces a deterministic, zero-LLM summary.
    * ``save_reflection`` persists the synthesized result — whether that
      result came from a runtime LLM (e.g., a Claude Code session on the
      Max subscription) or from ``template_summary``.

Public types:
    SessionContext, SessionReflection — frozen dataclasses at the boundary.

Public functions:
    gather_session_context(db, session_id, event_limit, decision_limit)
    save_reflection(db, session_id, what_went_well, what_to_improve,
                    apply_next_session, auto_generated)
    template_summary(context)
    list_reflections(db, session_id=None, limit=20)
"""

from central_brain.reflection.session import (
    SessionContext,
    SessionReflection,
    gather_session_context,
    list_reflections,
    save_reflection,
    template_summary,
)

__all__ = [
    "SessionContext",
    "SessionReflection",
    "gather_session_context",
    "list_reflections",
    "save_reflection",
    "template_summary",
]
