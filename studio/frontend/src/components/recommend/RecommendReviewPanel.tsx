/**
 * Review panel for recommended agents and phases.
 * Shows selectable cards with an "Apply Selected" action button.
 */

import { useState } from "react";
import type { AgentSpec, PhaseSpec } from "../../types";
import { AgentRecommendCard } from "./AgentRecommendCard";
import { PhaseRecommendCard } from "./PhaseRecommendCard";

interface RecommendedAgent {
  readonly agent: AgentSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface RecommendedPhase {
  readonly phase: PhaseSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface RecommendationResult {
  readonly agents: readonly RecommendedAgent[];
  readonly phases: readonly RecommendedPhase[];
  readonly team_name_suggestion: string;
  readonly team_description_suggestion: string;
  readonly source: string;
}

interface RecommendReviewPanelProps {
  readonly result: RecommendationResult;
  readonly onApply: (agents: readonly AgentSpec[], phases: readonly PhaseSpec[]) => void;
  readonly onEditAgent: (agent: AgentSpec, index: number) => void;
  readonly applying: boolean;
}

export function RecommendReviewPanel({
  result,
  onApply,
  onEditAgent,
  applying,
}: RecommendReviewPanelProps) {
  const [selectedAgents, setSelectedAgents] = useState<Set<number>>(
    () => new Set(result.agents.map((_, i) => i)),
  );
  const [selectedPhases, setSelectedPhases] = useState<Set<number>>(
    () => new Set(result.phases.map((_, i) => i)),
  );

  function toggleAgent(index: number) {
    setSelectedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  function togglePhase(index: number) {
    setSelectedPhases((prev) => {
      const next = new Set(prev);
      if (next.has(index)) {
        next.delete(index);
      } else {
        next.add(index);
      }
      return next;
    });
  }

  function selectAllAgents() {
    setSelectedAgents(new Set(result.agents.map((_, i) => i)));
  }

  function deselectAllAgents() {
    setSelectedAgents(new Set());
  }

  function selectAllPhases() {
    setSelectedPhases(new Set(result.phases.map((_, i) => i)));
  }

  function deselectAllPhases() {
    setSelectedPhases(new Set());
  }

  function handleApply() {
    const agents = result.agents
      .filter((_, i) => selectedAgents.has(i))
      .map((r) => r.agent);
    const phases = result.phases
      .filter((_, i) => selectedPhases.has(i))
      .map((r) => r.phase);
    onApply(agents, phases);
  }

  const totalSelected = selectedAgents.size + selectedPhases.size;

  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="bg-white rounded-lg shadow p-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-semibold text-gray-900">
              Recommendations
            </h3>
            <p className="text-sm text-gray-500">
              {result.agents.length} agents, {result.phases.length} phases suggested
              {result.source === "codebase" ? " from codebase analysis" : " from description"}
            </p>
            {result.team_name_suggestion && (
              <p className="text-sm text-gray-400 mt-1">
                Suggested team name: <span className="font-medium text-gray-600">{result.team_name_suggestion}</span>
              </p>
            )}
          </div>
          <button
            onClick={handleApply}
            disabled={totalSelected === 0 || applying}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {applying ? "Applying..." : `Apply Selected (${totalSelected})`}
          </button>
        </div>
      </div>

      {/* Agents */}
      {result.agents.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-md font-semibold text-gray-800">
              Recommended Agents ({result.agents.length})
            </h3>
            <div className="flex gap-2">
              <button
                onClick={selectAllAgents}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                Select all
              </button>
              <span className="text-xs text-gray-300">|</span>
              <button
                onClick={deselectAllAgents}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                Deselect all
              </button>
            </div>
          </div>
          <div className="space-y-3">
            {result.agents.map((rec, i) => (
              <AgentRecommendCard
                key={rec.agent.id}
                rec={rec}
                selected={selectedAgents.has(i)}
                onToggle={() => toggleAgent(i)}
                onEdit={() => onEditAgent(rec.agent, i)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Phases */}
      {result.phases.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-md font-semibold text-gray-800">
              Recommended Phases ({result.phases.length})
            </h3>
            <div className="flex gap-2">
              <button
                onClick={selectAllPhases}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                Select all
              </button>
              <span className="text-xs text-gray-300">|</span>
              <button
                onClick={deselectAllPhases}
                className="text-xs text-indigo-600 hover:text-indigo-800"
              >
                Deselect all
              </button>
            </div>
          </div>
          <div className="space-y-3">
            {result.phases.map((rec, i) => (
              <PhaseRecommendCard
                key={rec.phase.id}
                rec={rec}
                selected={selectedPhases.has(i)}
                onToggle={() => togglePhase(i)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
