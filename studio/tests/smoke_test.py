"""Quick smoke test for the Studio pipeline."""

from pathlib import Path
from studio.templates.manager import import_template
from studio.generation.generator import generate_profile_yaml
from studio.validation.validator import validate_team
from studio.graph.validator import validate_graph

# Import content-moderation template
team = import_template(Path("profiles/content-moderation"))
print(f"Imported: {team.name}")
print(f"  Agents: {len(team.agents)}")
print(f"  Phases: {len(team.workflow.phases)}")
print(f"  Policies: {len(team.governance.policies)}")
print(f"  Work Items: {len(team.work_item_types)}")

# Validate
result = validate_team(team)
print(f"Validation: valid={result.is_valid}, errors={len(result.errors)}, warnings={len(result.warnings)}")
for e in result.errors:
    print(f"  ERROR: {e.message}")
for w in result.warnings:
    print(f"  WARN: {w.message}")

# Graph validation
graph = validate_graph(team.workflow)
print(f"Graph: valid={graph.is_valid}, nodes={len(graph.nodes)}, edges={len(graph.edges)}")

# Generate YAML
yamls = generate_profile_yaml(team)
for name, content in yamls.items():
    print(f"Generated {name}: {len(content)} bytes")
