"""Recommendation engine — matches project descriptions or codebase analysis to archetypes.

Three-tier strategy:
1. Static domain catalog (trading, healthcare, legal, etc.) — instant, no API cost
2. LLM-generated domain agents — for any domain not in the static catalog
3. Software dev archetypes — when the description is about building software

LLM-generated domains are cached so subsequent requests are instant.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from studio.ir.models import AgentSpec, LLMSpec, PhaseSpec, RetryPolicySpec
from studio.recommend.archetypes import (
    SOFTWARE_DEV_ARCHETYPES,
    Archetype,
    detect_domain,
    get_archetypes_for_domain,
    get_phase_order,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RecommendedAgent(BaseModel):
    """An agent recommendation with confidence and rationale."""

    agent: AgentSpec
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class RecommendedPhase(BaseModel):
    """A phase recommendation with confidence and rationale."""

    phase: PhaseSpec
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


class RecommendationResult(BaseModel):
    """Complete recommendation output."""

    agents: list[RecommendedAgent] = Field(default_factory=list)
    phases: list[RecommendedPhase] = Field(default_factory=list)
    team_name_suggestion: str = ""
    team_description_suggestion: str = ""
    source: str = "greenfield"
    detected_domain: str = ""  # empty = software dev / no domain detected


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_DEFAULT_LLM = LLMSpec(provider="openai", model="gpt-4o")
_DEFAULT_RETRY = RetryPolicySpec()


def _tokenize(text: str) -> tuple[set[str], str]:
    """Lowercase tokenization returning both individual words and the full text."""
    lower = text.lower()
    words = set(re.findall(r"[a-z0-9/\-]+", lower))
    return words, lower


def _score_archetype(tokens: set[str], full_text: str, archetype: Archetype) -> float:
    """Score an archetype against tokenized input. Higher = better match."""
    matches = 0
    for kw in archetype.keywords:
        kw_lower = kw.lower()
        if " " in kw_lower:
            # Multi-word keyword: check if it appears in the full text
            if kw_lower in full_text:
                matches += 1
            else:
                # Check if all words of the keyword appear individually
                kw_words = kw_lower.split()
                if all(w in tokens for w in kw_words):
                    matches += 0.7
        elif kw_lower in tokens:
            matches += 1
        else:
            # Partial match: keyword is substring of a token or vice versa
            for token in tokens:
                if kw_lower in token or token in kw_lower:
                    matches += 0.5
                    break
    if not archetype.keywords:
        # LLM-generated archetypes have no keywords — return 0 (they're
        # included directly, not scored)
        return 0.0
    # Use a balanced score: reward matches but don't over-penalize large keyword lists
    # Cap the denominator so archetypes with many keywords aren't disadvantaged
    denominator = min(len(archetype.keywords), 4) * 0.5
    return matches / denominator


def _build_agent(archetype: Archetype) -> AgentSpec:
    """Create an AgentSpec from an archetype template."""
    return AgentSpec(
        id=archetype.id,
        name=archetype.name,
        description=archetype.description,
        system_prompt=archetype.system_prompt,
        skills=archetype.skills,
        phases=[archetype.default_phase],
        llm=_DEFAULT_LLM,
        retry_policy=_DEFAULT_RETRY,
    )


def _build_phases(
    matched: list[tuple[Archetype, float, str]],
    domain: str | None = None,
) -> list[RecommendedPhase]:
    """Generate deduplicated, ordered, wired phases from matched archetypes."""
    phase_map: dict[str, tuple[float, str, list[str]]] = {}

    for arch, conf, reason in matched:
        pid = arch.default_phase
        if pid in phase_map:
            existing_conf, _, agents = phase_map[pid]
            if arch.id not in agents:
                agents.append(arch.id)
            phase_map[pid] = (max(existing_conf, conf), reason, agents)
        else:
            phase_map[pid] = (conf, reason, [arch.id])

    # Sort by canonical order for the detected domain
    sorted_phases = sorted(phase_map.items(), key=lambda kv: get_phase_order(kv[0], domain))

    result: list[RecommendedPhase] = []
    for i, (pid, (conf, reason, agents)) in enumerate(sorted_phases):
        on_success = sorted_phases[i + 1][0] if i + 1 < len(sorted_phases) else ""
        on_failure = pid  # retry self on failure

        is_terminal = i == len(sorted_phases) - 1
        phase = PhaseSpec(
            id=pid,
            name=pid.replace("-", " ").replace("_", " ").title(),
            description=f"Phase for {pid}",
            order=i + 1,
            agents=agents,
            on_success="" if is_terminal else on_success,
            on_failure="" if is_terminal else on_failure,
            is_terminal=is_terminal,
        )
        result.append(
            RecommendedPhase(phase=phase, confidence=min(conf, 1.0), reason=reason)
        )

    return result


def _suggest_team_name(description: str) -> str:
    """Generate a team name suggestion from the description."""
    words = description.strip().split()
    if len(words) <= 4:
        return description.strip().title() + " Team"
    return " ".join(words[:4]).title() + " Team"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_from_description(description: str) -> RecommendationResult:
    """Recommend agents and phases from a freeform project description.

    Tokenizes the description, scores each archetype by keyword overlap,
    includes archetypes scoring above threshold, and generates wired phases.
    """
    if not description.strip():
        return RecommendationResult(
            source="greenfield",
            team_name_suggestion="",
            team_description_suggestion="",
        )

    tokens, full_text = _tokenize(description)
    logger.info("Greenfield tokens: %s", tokens)

    # Detect if the description is about a specific domain
    # Check static catalogs first, then persistent cache
    domain_catalog = detect_domain(tokens, full_text)
    if not domain_catalog:
        from studio.recommend.domain_cache import get_cached
        # Check if any cached domain name appears in the description
        for token in tokens:
            cached = get_cached(token)
            if cached:
                domain_catalog = cached
                break
    detected_domain = domain_catalog.domain if domain_catalog else None

    if domain_catalog:
        logger.info("Detected domain: %s", detected_domain)
        # Use domain-specific archetypes — include all of them with high confidence
        # since the domain was explicitly detected
        archetypes = domain_catalog.archetypes
        matched: list[tuple[Archetype, float, str]] = []
        for arch in archetypes:
            score = _score_archetype(tokens, full_text, arch)
            # For domain archetypes, use a lower threshold since the domain itself
            # was already matched — include all archetypes from the domain with
            # at least a base confidence
            effective_score = max(score, 0.6)  # minimum 60% for domain archetypes
            reason = f"Recommended for {domain_catalog.domain} domain: {arch.description}"
            matched.append((arch, min(effective_score, 1.0), reason))
    else:
        # Fall back to software development archetypes
        archetypes = SOFTWARE_DEV_ARCHETYPES
        matched = []
        for arch in archetypes:
            score = _score_archetype(tokens, full_text, arch)
            if score > 0.3:
                reason = f"Matched keywords from description for {arch.name.lower()}"
                matched.append((arch, score, reason))

        # Boost management archetypes when 2+ non-management agents recommended
        dev_count = sum(1 for a, _, _ in matched if a.category != "management")
        if dev_count >= 2:
            for arch in archetypes:
                if arch.category == "management" and not any(a.id == arch.id for a, _, _ in matched):
                    matched.append((arch, 0.5, f"Added {arch.name} because project has {dev_count}+ development agents"))

    # Sort by score descending
    matched.sort(key=lambda x: x[1], reverse=True)

    agents = [
        RecommendedAgent(
            agent=_build_agent(arch),
            confidence=min(score, 1.0),
            reason=reason,
        )
        for arch, score, reason in matched
    ]

    phases = _build_phases(matched, domain=detected_domain)

    return RecommendationResult(
        agents=agents,
        phases=phases,
        team_name_suggestion=_suggest_team_name(description),
        team_description_suggestion=description.strip(),
        source="greenfield",
        detected_domain=detected_domain or "",
    )


def recommend_from_codebase(analysis: dict[str, Any]) -> RecommendationResult:
    """Recommend agents and phases from a codebase analysis JSON.

    First checks if the project name/description indicates a specific domain
    (e.g., "trading", "healthcare"). If so, returns domain-specific agents.
    Otherwise falls back to software dev structural mapping.
    """
    project_name = analysis.get("project_name", "")
    description = analysis.get("description", "")
    combined_text = f"{project_name} {description}"

    # Try domain detection from project name + description
    tokens, full_text = _tokenize(combined_text)

    domain_catalog = detect_domain(tokens, full_text)
    if not domain_catalog:
        from studio.recommend.domain_cache import get_cached
        for token in tokens:
            cached = get_cached(token)
            if cached:
                domain_catalog = cached
                break

    if domain_catalog:
        # Domain detected — return domain-specific agents
        logger.info("Codebase analysis: detected domain '%s' from project metadata", domain_catalog.domain)
        matched: list[tuple[Archetype, float, str]] = []
        for arch in domain_catalog.archetypes:
            reason = f"Recommended for {domain_catalog.domain} domain based on codebase analysis: {arch.description}"
            matched.append((arch, 0.8, reason))

        matched.sort(key=lambda x: x[1], reverse=True)
        agents = [
            RecommendedAgent(agent=_build_agent(arch), confidence=min(score, 1.0), reason=reason)
            for arch, score, reason in matched
        ]
        phases = _build_phases(matched, domain=domain_catalog.domain)

        return RecommendationResult(
            agents=agents,
            phases=phases,
            team_name_suggestion=f"{project_name or 'Analyzed Project'} Team",
            team_description_suggestion=description or f"Agent team for {project_name}",
            source="codebase",
            detected_domain=domain_catalog.domain,
        )

    # No domain detected — fall back to software dev structural mapping
    return _recommend_software_dev_from_codebase(analysis)


def _recommend_software_dev_from_codebase(analysis: dict[str, Any]) -> RecommendationResult:
    """Software development structural mapping (original codebase analysis logic)."""
    matched: list[tuple[Archetype, float, str]] = []
    arch_map = {a.id: a for a in SOFTWARE_DEV_ARCHETYPES}

    tech_stack = analysis.get("tech_stack", {})
    components = analysis.get("components", [])
    apis = analysis.get("apis", [])
    database = analysis.get("database", {})
    testing = analysis.get("testing", {})
    ci_cd = analysis.get("ci_cd", {})
    issues = analysis.get("known_issues", [])
    documentation = analysis.get("documentation", {})

    if apis or tech_stack.get("backend"):
        arch = arch_map["backend-dev-agent"]
        conf = 0.9 if apis else 0.7
        matched.append((arch, conf, "Codebase has API endpoints that need backend development"))

    frontend_techs = tech_stack.get("frontend", [])
    has_frontend = bool(frontend_techs) or any(
        c.get("type", "").lower() in ("frontend", "ui", "web")
        for c in components
        if isinstance(c, dict)
    )
    if has_frontend:
        arch = arch_map["frontend-dev-agent"]
        matched.append((arch, 0.85, "Codebase has frontend components"))

    if database and (database.get("type") or database.get("tables")):
        if not any(a.id == "backend-dev-agent" for a, _, _ in matched):
            arch = arch_map["backend-dev-agent"]
            matched.append((arch, 0.8, "Codebase has database configuration requiring backend work"))

    has_tests = testing.get("has_tests", False) if isinstance(testing, dict) else bool(testing)
    coverage = testing.get("coverage_percent", 100) if isinstance(testing, dict) else 100
    if not has_tests:
        arch = arch_map["tester-agent"]
        matched.append((arch, 0.95, "No tests detected — testing agent highly recommended"))
    elif isinstance(coverage, (int, float)) and coverage < 50:
        arch = arch_map["tester-agent"]
        matched.append((arch, 0.8, f"Test coverage is low ({coverage}%) — testing agent recommended"))

    if components or apis:
        arch = arch_map["code-reviewer-agent"]
        matched.append((arch, 0.7, "Code review recommended for codebase quality"))

    has_cicd = ci_cd.get("configured", False) if isinstance(ci_cd, dict) else bool(ci_cd)
    if has_cicd:
        arch = arch_map["devops-agent"]
        matched.append((arch, 0.8, "CI/CD pipeline detected — DevOps agent can manage deployments"))
    elif len(components) >= 2:
        arch = arch_map["devops-agent"]
        matched.append((arch, 0.6, "Multiple components detected — DevOps agent recommended for deployment"))

    high_issues = [
        i for i in issues
        if isinstance(i, dict) and i.get("severity", "").lower() in ("high", "critical")
    ]
    if high_issues:
        arch = arch_map["security-scanner-agent"]
        matched.append((arch, 0.9, f"{len(high_issues)} high/critical issues found — security scanning recommended"))
    elif apis:
        arch = arch_map["security-scanner-agent"]
        matched.append((arch, 0.5, "APIs present — security review recommended"))

    if len(components) >= 3 or (apis and has_frontend):
        arch = arch_map["architect-agent"]
        matched.append((arch, 0.75, "Complex codebase with multiple components — architect recommended"))

    has_docs = documentation.get("has_readme", False) if isinstance(documentation, dict) else bool(documentation)
    if not has_docs:
        arch = arch_map["technical-writer-agent"]
        matched.append((arch, 0.7, "Documentation gaps detected — technical writer recommended"))

    # Deduplicate
    seen: dict[str, int] = {}
    deduped: list[tuple[Archetype, float, str]] = []
    for arch, conf, reason in matched:
        if arch.id in seen:
            idx = seen[arch.id]
            if conf > deduped[idx][1]:
                deduped[idx] = (arch, conf, reason)
        else:
            seen[arch.id] = len(deduped)
            deduped.append((arch, conf, reason))

    matched = deduped
    matched.sort(key=lambda x: x[1], reverse=True)

    agents = [
        RecommendedAgent(agent=_build_agent(arch), confidence=min(score, 1.0), reason=reason)
        for arch, score, reason in matched
    ]
    phases = _build_phases(matched)

    project_name = analysis.get("project_name", "Analyzed Project")
    return RecommendationResult(
        agents=agents,
        phases=phases,
        team_name_suggestion=f"{project_name} Team",
        team_description_suggestion=analysis.get("description", f"Agent team for {project_name}"),
        source="codebase",
    )


def generate_codebase_prompt(
    project_description: str | None = None,
    focus_areas: list[str] | None = None,
) -> dict[str, str]:
    """Generate a prompt the user can paste into their coding assistant.

    Returns prompt text and usage instructions. The coding assistant will
    analyze the codebase and return a JSON object matching the CodebaseAnalysis
    schema.
    """
    focus_section = ""
    if focus_areas:
        focus_section = f"""
Pay special attention to these areas: {', '.join(focus_areas)}.
"""

    project_section = ""
    if project_description:
        project_section = f"""
Project context: {project_description}
"""

    prompt = f"""Analyze this codebase and return a JSON object with the following structure. ONLY describe what actually exists — do not suggest improvements or additions.
{project_section}{focus_section}
Return ONLY valid JSON matching this schema:

```json
{{
  "project_name": "string - the project name",
  "description": "string - brief project description",
  "tech_stack": {{
    "languages": ["string - programming languages used"],
    "frontend": ["string - frontend frameworks/libraries"],
    "backend": ["string - backend frameworks/libraries"],
    "databases": ["string - databases used"],
    "infrastructure": ["string - cloud/infra tools"]
  }},
  "components": [
    {{
      "name": "string - component name",
      "type": "string - frontend|backend|shared|infrastructure",
      "path": "string - relative path",
      "description": "string - what it does"
    }}
  ],
  "apis": [
    {{
      "path": "string - API route",
      "method": "string - HTTP method",
      "description": "string - what it does"
    }}
  ],
  "database": {{
    "type": "string - database type or null",
    "tables": ["string - table/collection names"],
    "orm": "string - ORM used or null"
  }},
  "testing": {{
    "has_tests": true,
    "frameworks": ["string - test frameworks"],
    "coverage_percent": 0
  }},
  "ci_cd": {{
    "configured": true,
    "platform": "string - CI platform or null",
    "pipelines": ["string - pipeline names"]
  }},
  "documentation": {{
    "has_readme": true,
    "has_api_docs": false,
    "has_architecture_docs": false
  }},
  "known_issues": [
    {{
      "description": "string - issue description",
      "severity": "string - low|medium|high|critical",
      "area": "string - affected area"
    }}
  ]
}}
```

Analyze the codebase thoroughly. Look at:
1. File structure and organization
2. Package manifests (package.json, requirements.txt, go.mod, etc.)
3. Source code for frameworks, patterns, and libraries used
4. Test directories and test configuration
5. CI/CD configuration files (.github/workflows, Jenkinsfile, etc.)
6. Database migrations, schemas, or ORM models
7. API route definitions
8. Documentation files

Return ONLY the JSON object, no additional text."""

    instructions = (
        "1. Copy the prompt below\n"
        "2. Paste it into your coding assistant (Claude Code, Cursor, etc.) while in your project directory\n"
        "3. The assistant will analyze your codebase and return a JSON object\n"
        "4. Copy the JSON response and paste it into the text area above\n"
        "5. Click 'Analyze' to get agent recommendations"
    )

    return {"prompt": prompt, "instructions": instructions}


# ---------------------------------------------------------------------------
# LLM-powered generation (async)
# ---------------------------------------------------------------------------

async def recommend_from_description_with_llm(
    description: str,
    api_keys: dict[str, str],
    endpoints: dict[str, str],
) -> RecommendationResult | None:
    """Generate domain-specific recommendations using an LLM.

    Called when static catalogs don't match. Results are cached and persisted
    so future requests for the same domain are instant.
    """
    from studio.recommend.llm_generator import generate_from_llm
    from studio.recommend.domain_cache import cache_from_llm_result

    llm_result = await generate_from_llm(description, api_keys, endpoints)
    if not llm_result:
        return None

    # Cache the generated domain for future use
    catalog = cache_from_llm_result(llm_result)
    if not catalog:
        return None

    # Build recommendation from the cached catalog
    matched: list[tuple[Archetype, float, str]] = []
    for arch in catalog.archetypes:
        # Use confidence from the LLM result if available
        agent_data = next(
            (a for a in llm_result.get("agents", []) if isinstance(a, dict) and a.get("id") == arch.id),
            None,
        )
        confidence = agent_data.get("confidence", 0.7) if agent_data else 0.7
        reason = agent_data.get("reason", f"AI-generated for {catalog.domain} domain") if agent_data else f"AI-generated for {catalog.domain} domain"
        matched.append((arch, min(confidence, 1.0), reason))

    matched.sort(key=lambda x: x[1], reverse=True)

    agents = [
        RecommendedAgent(
            agent=_build_agent(arch),
            confidence=min(score, 1.0),
            reason=reason,
        )
        for arch, score, reason in matched
    ]

    phases = _build_phases(matched, domain=catalog.domain)

    team_name = llm_result.get("team_name", _suggest_team_name(description))
    team_desc = llm_result.get("team_description", description.strip())

    return RecommendationResult(
        agents=agents,
        phases=phases,
        team_name_suggestion=team_name,
        team_description_suggestion=team_desc,
        source="greenfield",
    )
