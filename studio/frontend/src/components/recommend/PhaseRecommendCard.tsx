/**
 * Individual phase recommendation card with checkbox, agent assignments, and transitions.
 */

import type { PhaseSpec } from "../../types";

interface RecommendedPhase {
  readonly phase: PhaseSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface PhaseRecommendCardProps {
  readonly rec: RecommendedPhase;
  readonly selected: boolean;
  readonly onToggle: () => void;
}

function confidenceBadge(confidence: number) {
  if (confidence > 0.7) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-green-100 text-green-700">
        {Math.round(confidence * 100)}%
      </span>
    );
  }
  if (confidence >= 0.4) {
    return (
      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-yellow-100 text-yellow-700">
        {Math.round(confidence * 100)}%
      </span>
    );
  }
  return (
    <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
      {Math.round(confidence * 100)}%
    </span>
  );
}

export function PhaseRecommendCard({ rec, selected, onToggle }: PhaseRecommendCardProps) {
  const { phase, confidence, reason } = rec;

  return (
    <div
      className={`border rounded-lg p-4 transition-colors ${
        selected ? "border-indigo-400 bg-indigo-50" : "border-gray-200 bg-white"
      }`}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={selected}
          onChange={onToggle}
          className="mt-1 h-4 w-4 text-indigo-600 rounded border-gray-300"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <h4 className="text-sm font-semibold text-gray-900">{phase.name}</h4>
            {confidenceBadge(confidence)}
            <span className="text-xs text-gray-400">Order: {phase.order}</span>
            {phase.is_terminal && (
              <span className="px-2 py-0.5 bg-red-100 text-red-700 rounded text-xs">
                Terminal
              </span>
            )}
          </div>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{phase.id}</p>
          <p className="text-xs text-gray-400 mt-1 italic">{reason}</p>

          <div className="flex flex-wrap gap-2 mt-2">
            {phase.agents.map((agentId) => (
              <span
                key={agentId}
                className="px-2 py-0.5 bg-blue-100 text-blue-700 rounded text-xs"
              >
                {agentId}
              </span>
            ))}
          </div>

          {(phase.on_success || phase.on_failure) && (
            <div className="flex gap-4 mt-2 text-xs text-gray-500">
              {phase.on_success && (
                <span>
                  On success: <span className="font-mono text-green-600">{phase.on_success}</span>
                </span>
              )}
              {phase.on_failure && (
                <span>
                  On failure: <span className="font-mono text-red-600">{phase.on_failure}</span>
                </span>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
