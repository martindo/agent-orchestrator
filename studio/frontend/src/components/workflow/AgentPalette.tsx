import type { AgentSpec } from "../../types";

interface AgentPaletteProps {
  readonly agents: readonly AgentSpec[];
  readonly onCreateAgent: () => void;
  readonly onEditAgent: (index: number) => void;
  readonly onDeleteAgent: (index: number) => void;
}

export function AgentPalette({
  agents,
  onCreateAgent,
  onEditAgent,
  onDeleteAgent,
}: AgentPaletteProps) {
  function onDragStart(
    event: React.DragEvent<HTMLDivElement>,
    agentId: string
  ) {
    event.dataTransfer.setData("application/agent-id", agentId);
    event.dataTransfer.effectAllowed = "copy";
  }

  return (
    <div className="w-52 bg-gray-50 border-r border-gray-200 p-3 overflow-y-auto flex-shrink-0 flex flex-col">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
          Agents
        </h3>
        <button
          onClick={onCreateAgent}
          className="text-xs bg-indigo-600 text-white px-2 py-1 rounded hover:bg-indigo-700 font-medium"
        >
          + New
        </button>
      </div>

      {agents.length === 0 ? (
        <div className="text-center py-6">
          <p className="text-xs text-gray-400 mb-2">No agents yet.</p>
          <button
            onClick={onCreateAgent}
            className="text-xs text-indigo-600 hover:text-indigo-800 font-medium"
          >
            Create your first agent
          </button>
        </div>
      ) : (
        <div className="space-y-2 flex-1">
          {agents.map((agent, i) => (
            <div
              key={agent.id}
              draggable
              onDragStart={(e) => onDragStart(e, agent.id)}
              className="bg-white border border-gray-200 rounded-md px-3 py-2 text-sm cursor-grab active:cursor-grabbing hover:border-indigo-300 hover:shadow-sm transition-all group"
            >
              <div className="flex items-center justify-between">
                <div className="font-medium text-gray-800 text-xs truncate">
                  {agent.name || agent.id}
                </div>
                <div className="hidden group-hover:flex gap-1 shrink-0 ml-1">
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onEditAgent(i);
                    }}
                    className="text-[10px] text-indigo-500 hover:text-indigo-700"
                    title="Edit"
                  >
                    edit
                  </button>
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onDeleteAgent(i);
                    }}
                    className="text-[10px] text-red-400 hover:text-red-600"
                    title="Delete"
                  >
                    del
                  </button>
                </div>
              </div>
              {!agent.enabled && (
                <span className="text-[9px] text-gray-400">disabled</span>
              )}
              <div className="text-[10px] text-gray-400 mt-0.5 truncate">
                {agent.llm.provider}/{agent.llm.model}
              </div>
              {agent.skills.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {agent.skills.slice(0, 3).map((skill) => (
                    <span
                      key={skill}
                      className="text-[9px] px-1 py-0.5 rounded bg-gray-100 text-gray-500"
                    >
                      {skill}
                    </span>
                  ))}
                  {agent.skills.length > 3 && (
                    <span className="text-[9px] text-gray-400">
                      +{agent.skills.length - 3}
                    </span>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <div className="mt-3 pt-3 border-t border-gray-200 text-[10px] text-gray-400 leading-tight">
        Drag an agent onto a phase node to assign it.
      </div>
    </div>
  );
}
