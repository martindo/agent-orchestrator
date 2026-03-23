"""Knowledge subsystem — shared memory and knowledge management for agents."""

from agent_orchestrator.knowledge.context_memory import ContextMemory
from agent_orchestrator.knowledge.embedding import EmbeddingService, cosine_similarity
from agent_orchestrator.knowledge.models import MemoryQuery, MemoryRecord, MemoryType
from agent_orchestrator.knowledge.store import KnowledgeStore

__all__ = [
    "ContextMemory",
    "EmbeddingService",
    "KnowledgeStore",
    "MemoryQuery",
    "MemoryRecord",
    "MemoryType",
    "cosine_similarity",
]
