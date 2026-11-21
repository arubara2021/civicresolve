"""Runtime selection.

The application depends only on the protocol types defined in ports.py. This module
is the single place that maps the CIVIC_AGENT_RUNTIME setting to an implementation,
so switching runtimes requires no other code change.

The default is the direct Gemini implementation. ADK and LangGraph are drop-in
alternatives that share the same tools and the same output schemas.
"""

from __future__ import annotations

from collections.abc import Callable

from app.core.config import AgentRuntime, Settings, get_settings
from app.core.logging import get_logger

from .gemini_direct import GeminiAuditorAgent, GeminiTriageAgent
from .ports import AuditorAgent, TriageAgent

log = get_logger(__name__)

TriageFactory = Callable[[], TriageAgent]
AuditorFactory = Callable[[], AuditorAgent]


def _adk_factories() -> tuple[TriageFactory, AuditorFactory]:
    """Lazy import so a missing google-adk does not break the default runtime."""
    try:
        from .adk_agent import ADKAuditorAgent, ADKTriageAgent
    except ImportError as exc:
        raise RuntimeError("AGENT_RUNTIME=adk requires google-adk to be installed.") from exc
    return lambda: ADKTriageAgent(), lambda: ADKAuditorAgent()


def _langgraph_factories() -> tuple[TriageFactory, AuditorFactory]:
    """Lazy import so a missing langgraph does not break the default runtime."""
    try:
        from .langgraph_agent import LangGraphAuditorAgent, LangGraphTriageAgent
    except ImportError as exc:
        raise RuntimeError("AGENT_RUNTIME=langgraph requires langgraph to be installed.") from exc
    return lambda: LangGraphTriageAgent(), lambda: LangGraphAuditorAgent()


_FACTORIES: dict[AgentRuntime, tuple[TriageFactory, AuditorFactory]] = {
    AgentRuntime.DIRECT: (
        lambda: GeminiTriageAgent(),
        lambda: GeminiAuditorAgent(),
    ),
    AgentRuntime.ADK: _adk_factories,
    AgentRuntime.LANGGRAPH: _langgraph_factories,
}


def build_triage_agent(settings: Settings | None = None) -> TriageAgent:
    """Construct the triage agent for the configured runtime."""
    resolved = settings or get_settings()
    factory_entry = _FACTORIES[resolved.agent_runtime]
    if callable(factory_entry) and not isinstance(factory_entry, tuple):
        triage_factory, _auditor_factory = factory_entry()
    else:
        triage_factory, _auditor_factory = factory_entry
    log.debug("agents.triage_built", runtime=resolved.agent_runtime.value)
    return triage_factory()


def build_auditor_agent(settings: Settings | None = None) -> AuditorAgent:
    """Construct the auditor agent for the configured runtime."""
    resolved = settings or get_settings()
    factory_entry = _FACTORIES[resolved.agent_runtime]
    if callable(factory_entry) and not isinstance(factory_entry, tuple):
        _triage_factory, auditor_factory = factory_entry()
    else:
        _triage_factory, auditor_factory = factory_entry
    log.debug("agents.auditor_built", runtime=resolved.agent_runtime.value)
    return auditor_factory()

get_auditor_agent = build_auditor_agent

def build_auditor_agent(settings: Settings | None = None) -> AuditorAgent:
    """Construct the auditor agent for the configured runtime."""
    resolved = settings or get_settings()
    factory_entry = _FACTORIES[resolved.agent_runtime]
    if callable(factory_entry) and not isinstance(factory_entry, tuple):
        _triage_factory, auditor_factory = factory_entry()
    else:
        _triage_factory, auditor_factory = factory_entry
    log.debug("agents.auditor_built", runtime=resolved.agent_runtime.value)
    return auditor_factory()


# Convenience aliases — the intake and closure services import these names.
get_triage_agent = build_triage_agent
get_auditor_agent = build_auditor_agent