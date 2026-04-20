"""central-brain — cognitive primitives for AI agents.

Public API:
    Agent       — composed entry point over memory/decisions/reflection
    BrainConfig — brain.yaml schema (pydantic v2)
"""

from central_brain.agent import Agent
from central_brain.config import BrainConfig

__version__ = "0.0.1"

__all__ = ["Agent", "BrainConfig", "__version__"]
