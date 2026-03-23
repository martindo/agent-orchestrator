import { memo } from "react";
import { Handle, Position, type NodeProps, type Node } from "@xyflow/react";

export interface BuilderPhaseNodeData {
  label: string;
  isTerminal: boolean;
  requiresHuman: boolean;
  agents: readonly string[];
  agentNames: Record<string, string>;
  [key: string]: unknown;
}

function BuilderPhaseNodeInner({
  data,
  selected,
}: NodeProps<Node<BuilderPhaseNodeData>>) {
  const borderColor = data.isTerminal
    ? "border-red-400"
    : data.requiresHuman
      ? "border-yellow-400"
      : "border-indigo-400";

  const bgColor = data.isTerminal
    ? "bg-red-50"
    : data.requiresHuman
      ? "bg-yellow-50"
      : "bg-white";

  return (
    <div
      className={`px-4 py-3 rounded-lg border-2 shadow-sm min-w-[180px] ${borderColor} ${bgColor} ${
        selected ? "ring-2 ring-indigo-500 ring-offset-2" : ""
      }`}
    >
      {/* Target handle (top center) */}
      <Handle
        type="target"
        position={Position.Top}
        className="!bg-gray-400 !w-3 !h-3"
      />

      {/* Node content */}
      <div className="text-sm font-semibold text-center">{data.label}</div>

      {/* Agent chips */}
      {data.agents.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-2 justify-center">
          {data.agents.map((agentId) => (
            <span
              key={agentId}
              className="text-[10px] px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 border border-indigo-200"
            >
              {data.agentNames[agentId] ?? agentId}
            </span>
          ))}
        </div>
      )}

      {/* Badges row */}
      <div className="flex gap-1 mt-1 justify-center">
        {data.isTerminal && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-100 text-red-600">
            terminal
          </span>
        )}
        {data.requiresHuman && (
          <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-100 text-yellow-700">
            human
          </span>
        )}
      </div>

      {/* Source handles: success (bottom-left) and failure (bottom-right) */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="success"
        className="!bg-green-500 !w-3 !h-3 !-bottom-1.5"
        style={{ left: "35%" }}
        title="On Success"
      />
      <Handle
        type="source"
        position={Position.Bottom}
        id="failure"
        className="!bg-red-500 !w-3 !h-3 !-bottom-1.5"
        style={{ left: "65%" }}
        title="On Failure"
      />
    </div>
  );
}

export const BuilderPhaseNode = memo(BuilderPhaseNodeInner);
