"""brain-core — cognitive primitives for AI agents.

Public API:
    Agent       — composed entry point over memory/decisions/reflection
    BrainConfig — brain.yaml schema (pydantic v2)
"""

from brain_core.agent import Agent
from brain_core.config import BrainConfig

__version__ = "0.2.0"

__all__ = ["Agent", "BrainConfig", "__version__"]
