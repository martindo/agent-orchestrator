"""Round-trip test: import → export → re-import → compare."""

import tempfile
from pathlib import Path
from studio.templates.manager import import_template, export_template
from studio.conditions.builder import build_condition, parse_condition, validate_condition
from studio.conversion.converter import ir_to_profile_dict

# Round trip test
team1 = import_template(Path("profiles/content-moderation"))
with tempfile.TemporaryDirectory() as tmp:
    export_template(team1, Path(tmp))
    team2 = import_template(Path(tmp))

print(f"Original:    {team1.name}, {len(team1.agents)} agents, {len(team1.workflow.phases)} phases")
print(f"Round-trip:  {team2.name}, {len(team2.agents)} agents, {len(team2.workflow.phases)} phases")
assert team1.name == team2.name
assert len(team1.agents) == len(team2.agents)
assert len(team1.workflow.phases) == len(team2.workflow.phases)
assert len(team1.governance.policies) == len(team2.governance.policies)
assert len(team1.work_item_types) == len(team2.work_item_types)
print("Round-trip: PASS")

# Conditions builder
expr = build_condition("confidence", ">=", "0.8")
assert expr == "confidence >= 0.8"
parts = parse_condition(expr)
assert parts.field == "confidence"
assert parts.operator == ">="
assert parts.value == "0.8"
errors = validate_condition(expr)
assert len(errors) == 0
print("Conditions builder: PASS")

# IR to profile dict
d = ir_to_profile_dict(team1)
assert d["name"] == team1.name
assert len(d["agents"]) == 3
assert d["workflow"]["name"] == team1.workflow.name
print("IR to profile dict: PASS")

print("\nAll smoke tests passed!")
