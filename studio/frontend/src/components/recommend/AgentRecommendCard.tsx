/**
 * Individual agent recommendation card with checkbox, confidence badge, and edit button.
 */

import type { AgentSpec } from "../../types";

interface RecommendedAgent {
  readonly agent: AgentSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface AgentRecommendCardProps {
  readonly rec: RecommendedAgent;
  readonly selected: boolean;
  readonly onToggle: () => void;
  readonly onEdit: () => void;
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

export function AgentRecommendCard({ rec, selected, onToggle, onEdit }: AgentRecommendCardProps) {
  const { agent, confidence, reason } = rec;

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
            <h4 className="text-sm font-semibold text-gray-900">{agent.name}</h4>
            {confidenceBadge(confidence)}
          </div>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{agent.id}</p>
          <p className="text-sm text-gray-600 mt-1">{agent.description}</p>
          <p className="text-xs text-gray-400 mt-1 italic">{reason}</p>
          <div className="flex flex-wrap gap-1 mt-2">
            {agent.skills.map((skill) => (
              <span
                key={skill}
                className="px-2 py-0.5 bg-green-100 text-green-700 rounded text-xs"
              >
                {skill}
              </span>
            ))}
            {agent.phases.map((phase) => (
              <span
                key={phase}
                className="px-2 py-0.5 bg-purple-100 text-purple-700 rounded text-xs"
              >
                {phase}
              </span>
            ))}
          </div>
        </div>
        <button
          onClick={onEdit}
          className="text-xs text-indigo-600 hover:text-indigo-800 whitespace-nowrap"
        >
          Edit
        </button>
      </div>
    </div>
  );
}
