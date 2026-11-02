"""brain-core — cognitive primitives for AI agents.

Public API:
    Agent       — the five brain_* operations over every configured store
    BrainConfig — brain.yaml schema (pydantic v2)
"""

from brain_core.agent import Agent
from brain_core.config import BrainConfig

__version__ = "0.4.6"

__all__ = ["Agent", "BrainConfig", "__version__"]
