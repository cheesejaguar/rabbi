"""Multi-agent pipeline for processing Torah wisdom queries.

Messages flow through four sequential agents:
    PastoralContextAgent (emotional analysis) ->
    HalachicReasoningAgent (legal landscape) ->
    MoralEthicalAgent (harm prevention) ->
    MetaRabbinicVoiceAgent (final response).

Coordinated by RabbiOrchestrator.

The pipeline prioritizes pastoral responsibility over halachic maximalism.
If the MoralEthicalAgent flags concerns, the orchestrator triggers a
reconsideration loop back through the HalachicReasoningAgent with
adjusted context emphasizing compassion and leniency.
"""

from .base import BaseAgent, LLMMetrics, AgentContext
from .pastoral import PastoralContextAgent
from .halachic import HalachicReasoningAgent
from .moral import MoralEthicalAgent
from .voice import MetaRabbinicVoiceAgent
from .orchestrator import RabbiOrchestrator
from .rag import TextRetriever

__all__ = [
    "BaseAgent",
    "LLMMetrics",
    "AgentContext",
    "PastoralContextAgent",
    "HalachicReasoningAgent",
    "MoralEthicalAgent",
    "MetaRabbinicVoiceAgent",
    "RabbiOrchestrator",
    "TextRetriever",
]
