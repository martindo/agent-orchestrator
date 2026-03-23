import { useState, useMemo, useCallback } from "react";
import {
  ReactFlow,
  type Node,
  type Edge,
  type NodeTypes,
  Background,
  Controls,
  Handle,
  Position,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useTeamStore } from "../store/teamStore";
import { Modal } from "../components/common/Modal";
import type { PhaseSpec, StatusSpec, ConditionSpec, QualityGateSpec } from "../types";
import { WorkflowBuilder } from "../components/workflow/WorkflowBuilder";

/* ---------- Phase Flow Node ---------- */

interface PhaseNodeData {
  label: string;
  isTerminal: boolean;
  requiresHuman: boolean;
  agentCount: number;
  [key: string]: unknown;
}

function PhaseNode({ data }: NodeProps<Node<PhaseNodeData>>) {
  return (
    <div
      className={`px-4 py-3 rounded-lg border-2 shadow-sm min-w-[160px] text-center ${
        data.isTerminal
          ? "border-red-400 bg-red-50"
          : data.requiresHuman
            ? "border-yellow-400 bg-yellow-50"
            : "border-indigo-400 bg-white"
      }`}
    >
      <Handle type="target" position={Position.Top} className="!bg-gray-400" />
      <div className="text-sm font-semibold">{data.label}</div>
      <div className="text-xs text-gray-500 mt-1">
        {data.agentCount} agent{data.agentCount !== 1 ? "s" : ""}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-gray-400" />
    </div>
  );
}

const nodeTypes: NodeTypes = { phase: PhaseNode };

/* ---------- Defaults ---------- */

function emptyPhase(): PhaseSpec {
  return {
    id: "",
    name: "",
    description: "",
    order: 0,
    agents: [],
    parallel: false,
    entry_conditions: [],
    exit_conditions: [],
    quality_gates: [],
    critic_agent: null,
    critic_rubric: "",
    max_phase_retries: 0,
    retry_backoff_seconds: 0,
    on_success: "",
    on_failure: "",
    skippable: false,
    skip: false,
    is_terminal: false,
    requires_human: false,
    required_capabilities: [],
    expected_output_fields: [],
  };
}

function emptyStatus(): StatusSpec {
  return {
    id: "",
    name: "",
    description: "",
    is_initial: false,
    is_terminal: false,
    transitions_to: [],
  };
}

/* ---------- Page ---------- */

export function WorkflowPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const addPhase = useTeamStore((s) => s.addPhase);
  const updatePhase = useTeamStore((s) => s.updatePhase);
  const removePhase = useTeamStore((s) => s.removePhase);
  const addStatus = useTeamStore((s) => s.addStatus);
  const updateStatus = useTeamStore((s) => s.updateStatus);
  const removeStatus = useTeamStore((s) => s.removeStatus);

  const [tab, setTab] = useState<"phases" | "statuses" | "graph" | "builder">("phases");

  // Phase modal
  const [phaseModalOpen, setPhaseModalOpen] = useState(false);
  const [phaseEditIdx, setPhaseEditIdx] = useState<number | null>(null);
  const [phaseForm, setPhaseForm] = useState<PhaseSpec>(emptyPhase());
  const [phaseDeleteConfirm, setPhaseDeleteConfirm] = useState<number | null>(null);

  // Status modal
  const [statusModalOpen, setStatusModalOpen] = useState(false);
  const [statusEditIdx, setStatusEditIdx] = useState<number | null>(null);
  const [statusForm, setStatusForm] = useState<StatusSpec>(emptyStatus());
  const [statusDeleteConfirm, setStatusDeleteConfirm] = useState<number | null>(null);

  // Quality gate temp state
  const [newGateName, setNewGateName] = useState("");

  const agents = team?.agents ?? [];
  const phases = team?.workflow.phases ?? [];
  const statuses = team?.workflow.statuses ?? [];

  /* ----- Phase Helpers ----- */

  function openAddPhase() {
    setPhaseForm({ ...emptyPhase(), order: phases.length });
    setPhaseEditIdx(null);
    setPhaseModalOpen(true);
  }

  function openEditPhase(index: number) {
    const p = phases[index];
    if (!p) return;
    setPhaseForm(p);
    setPhaseEditIdx(index);
    setPhaseModalOpen(true);
  }

  function handleSavePhase() {
    if (phaseEditIdx !== null) {
      void updatePhase(phaseEditIdx, phaseForm);
    } else {
      void addPhase(phaseForm);
    }
    setPhaseModalOpen(false);
  }

  function togglePhaseAgent(agentId: string) {
    const current = [...phaseForm.agents];
    const idx = current.indexOf(agentId);
    if (idx >= 0) current.splice(idx, 1);
    else current.push(agentId);
    setPhaseForm({ ...phaseForm, agents: current });
  }

  function addQualityGate() {
    if (!newGateName.trim()) return;
    const gate: QualityGateSpec = {
      name: newGateName.trim(),
      description: "",
      conditions: [],
      on_failure: "block",
    };
    setPhaseForm({
      ...phaseForm,
      quality_gates: [...phaseForm.quality_gates, gate],
    });
    setNewGateName("");
  }

  function removeQualityGate(idx: number) {
    setPhaseForm({
      ...phaseForm,
      quality_gates: phaseForm.quality_gates.filter((_, i) => i !== idx),
    });
  }

  /* ----- Status Helpers ----- */

  function openAddStatus() {
    setStatusForm(emptyStatus());
    setStatusEditIdx(null);
    setStatusModalOpen(true);
  }

  function openEditStatus(index: number) {
    const s = statuses[index];
    if (!s) return;
    setStatusForm(s);
    setStatusEditIdx(index);
    setStatusModalOpen(true);
  }

  function handleSaveStatus() {
    if (statusEditIdx !== null) {
      void updateStatus(statusEditIdx, statusForm);
    } else {
      void addStatus(statusForm);
    }
    setStatusModalOpen(false);
  }

  function toggleStatusTransition(targetId: string) {
    const current = [...statusForm.transitions_to];
    const idx = current.indexOf(targetId);
    if (idx >= 0) current.splice(idx, 1);
    else current.push(targetId);
    setStatusForm({ ...statusForm, transitions_to: current });
  }

  /* ----- React Flow Graph ----- */

  const flowNodes = useMemo<Node<PhaseNodeData>[]>(() => {
    const sorted = [...phases].sort((a, b) => a.order - b.order);
    return sorted.map((p, i) => ({
      id: p.id,
      type: "phase" as const,
      position: { x: 250, y: i * 140 },
      data: {
        label: p.name || p.id,
        isTerminal: p.is_terminal,
        requiresHuman: p.requires_human,
        agentCount: p.agents.length,
      },
    }));
  }, [phases]);

  const flowEdges = useMemo<Edge[]>(() => {
    const edges: Edge[] = [];
    for (const p of phases) {
      if (p.on_success) {
        edges.push({
          id: `${p.id}-success-${p.on_success}`,
          source: p.id,
          target: p.on_success,
          label: "success",
          style: { stroke: "#22c55e" },
          labelStyle: { fill: "#16a34a", fontSize: 11 },
          animated: false,
        });
      }
      if (p.on_failure && p.on_failure !== p.on_success) {
        edges.push({
          id: `${p.id}-failure-${p.on_failure}`,
          source: p.id,
          target: p.on_failure,
          label: "failure",
          style: { stroke: "#ef4444" },
          labelStyle: { fill: "#dc2626", fontSize: 11 },
          animated: true,
        });
      }
    }
    return edges;
  }, [phases]);

  const onNodesChange = useCallback(() => {
    /* read-only graph */
  }, []);

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-4">Workflow</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 mb-4 border-b">
        {(["phases", "statuses", "graph", "builder"] as const).map((t) => (
          <button
            key={t}
            onClick={() => setTab(t)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === t
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.charAt(0).toUpperCase() + t.slice(1)}
          </button>
        ))}
      </div>

      {/* PHASES TAB */}
      {tab === "phases" && (
        <div>
          <div className="flex justify-end mb-3">
            <button
              onClick={openAddPhase}
              className="bg-indigo-600 text-white px-4 py-2 rounded-md hover:bg-indigo-700 text-sm font-medium"
            >
              + Add Phase
            </button>
          </div>

          {phases.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              No phases defined yet.
            </div>
          ) : (
            <div className="space-y-2">
              {phases.map((phase, i) => (
                <div
                  key={phase.id}
                  className="bg-white rounded-lg shadow p-4 flex items-start justify-between"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded font-mono">
                        #{phase.order}
                      </span>
                      <h3 className="font-semibold text-sm">{phase.name}</h3>
                      <span className="text-xs text-gray-400 font-mono">
                        {phase.id}
                      </span>
                      {phase.is_terminal && (
                        <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">
                          terminal
                        </span>
                      )}
                      {phase.requires_human && (
                        <span className="text-xs bg-yellow-100 text-yellow-700 px-2 py-0.5 rounded">
                          human
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mt-1">
                      {phase.description || "No description"}
                    </p>
                    <div className="text-xs text-gray-400 mt-1">
                      Agents: {phase.agents.length} | Gates:{" "}
                      {phase.quality_gates.length}
                      {phase.on_success && ` | On success: ${phase.on_success}`}
                      {phase.on_failure && ` | On failure: ${phase.on_failure}`}
                      {phase.required_capabilities.length > 0 && (() => {
                        const phaseAgentSkills = new Set(
                          agents
                            .filter((a) => phase.agents.includes(a.id))
                            .flatMap((a) => a.skills)
                        );
                        const uncovered = phase.required_capabilities.filter(
                          (cap) => !phaseAgentSkills.has(cap)
                        );
                        if (uncovered.length > 0) {
                          return (
                            <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded ml-1">
                              Missing: {uncovered.join(", ")}
                            </span>
                          );
                        }
                        return (
                          <span className="text-xs bg-green-100 text-green-600 px-2 py-0.5 rounded ml-1">
                            Capabilities covered
                          </span>
                        );
                      })()}
                    </div>
                  </div>
                  <div className="flex gap-2 ml-4 shrink-0">
                    <button
                      onClick={() => openEditPhase(i)}
                      className="text-sm text-indigo-600 hover:text-indigo-800"
                    >
                      Edit
                    </button>
                    {phaseDeleteConfirm === i ? (
                      <div className="flex gap-1">
                        <button
                          onClick={() => {
                            void removePhase(i);
                            setPhaseDeleteConfirm(null);
                          }}
                          className="text-sm text-red-600 font-medium"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setPhaseDeleteConfirm(null)}
                          className="text-sm text-gray-500"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setPhaseDeleteConfirm(i)}
                        className="text-sm text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* STATUSES TAB */}
      {tab === "statuses" && (
        <div>
          <div className="flex justify-end mb-3">
            <button
              onClick={openAddStatus}
              className="bg-indigo-600 text-white px-4 py-2 rounded-md hover:bg-indigo-700 text-sm font-medium"
            >
              + Add Status
            </button>
          </div>

          {statuses.length === 0 ? (
            <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
              No statuses defined yet.
            </div>
          ) : (
            <div className="space-y-2">
              {statuses.map((status, i) => (
                <div
                  key={status.id}
                  className="bg-white rounded-lg shadow p-4 flex items-start justify-between"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold text-sm">{status.name}</h3>
                      <span className="text-xs text-gray-400 font-mono">
                        {status.id}
                      </span>
                      {status.is_initial && (
                        <span className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded">
                          initial
                        </span>
                      )}
                      {status.is_terminal && (
                        <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">
                          terminal
                        </span>
                      )}
                    </div>
                    <p className="text-sm text-gray-600 mt-1">
                      {status.description || "No description"}
                    </p>
                    {status.transitions_to.length > 0 && (
                      <p className="text-xs text-gray-400 mt-1">
                        Transitions to: {status.transitions_to.join(", ")}
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2 ml-4 shrink-0">
                    <button
                      onClick={() => openEditStatus(i)}
                      className="text-sm text-indigo-600 hover:text-indigo-800"
                    >
                      Edit
                    </button>
                    {statusDeleteConfirm === i ? (
                      <div className="flex gap-1">
                        <button
                          onClick={() => {
                            void removeStatus(i);
                            setStatusDeleteConfirm(null);
                          }}
                          className="text-sm text-red-600 font-medium"
                        >
                          Confirm
                        </button>
                        <button
                          onClick={() => setStatusDeleteConfirm(null)}
                          className="text-sm text-gray-500"
                        >
                          Cancel
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setStatusDeleteConfirm(i)}
                        className="text-sm text-red-600 hover:text-red-800"
                      >
                        Delete
                      </button>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* GRAPH TAB */}
      {tab === "graph" && (
        <div className="bg-white rounded-lg shadow" style={{ height: 500 }}>
          {phases.length === 0 ? (
            <div className="flex items-center justify-center h-full text-gray-500">
              Add phases to see the workflow graph.
            </div>
          ) : (
            <ReactFlow
              nodes={flowNodes}
              edges={flowEdges}
              nodeTypes={nodeTypes}
              onNodesChange={onNodesChange}
              fitView
              proOptions={{ hideAttribution: true }}
            >
              <Background />
              <Controls />
            </ReactFlow>
          )}
        </div>
      )}

      {/* BUILDER TAB */}
      {tab === "builder" && <WorkflowBuilder />}

      {/* PHASE MODAL */}
      <Modal
        open={phaseModalOpen}
        onClose={() => setPhaseModalOpen(false)}
        title={phaseEditIdx !== null ? "Edit Phase" : "Add Phase"}
        wide
      >
        <div className="space-y-4">
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ID
              </label>
              <input
                type="text"
                value={phaseForm.id}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, id: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                disabled={phaseEditIdx !== null}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <input
                type="text"
                value={phaseForm.name}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, name: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Order
              </label>
              <input
                type="number"
                value={phaseForm.order}
                onChange={(e) =>
                  setPhaseForm({
                    ...phaseForm,
                    order: parseInt(e.target.value, 10) || 0,
                  })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                min={0}
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <input
              type="text"
              value={phaseForm.description}
              onChange={(e) =>
                setPhaseForm({ ...phaseForm, description: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>

          {/* Agents multi-select */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Agents
            </label>
            {agents.length === 0 ? (
              <p className="text-sm text-gray-400">No agents defined.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {agents.map((a) => {
                  const selected = phaseForm.agents.includes(a.id);
                  return (
                    <button
                      key={a.id}
                      type="button"
                      onClick={() => togglePhaseAgent(a.id)}
                      className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                        selected
                          ? "bg-indigo-100 border-indigo-400 text-indigo-700"
                          : "bg-gray-50 border-gray-300 text-gray-600 hover:bg-gray-100"
                      }`}
                    >
                      {a.name || a.id}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* Required Capabilities */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Required Capabilities
            </legend>
            {phaseForm.required_capabilities.length > 0 && (
              <div className="flex flex-wrap gap-2 mb-3">
                {phaseForm.required_capabilities.map((cap, ci) => (
                  <span
                    key={ci}
                    className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-blue-100 border border-blue-300 text-blue-700"
                  >
                    {cap}
                    <button
                      type="button"
                      onClick={() => {
                        setPhaseForm({
                          ...phaseForm,
                          required_capabilities: phaseForm.required_capabilities.filter(
                            (_, i) => i !== ci
                          ),
                        });
                      }}
                      className="text-blue-500 hover:text-blue-700"
                    >
                      x
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                id="newCapability"
                placeholder="Add capability (press Enter)"
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    const input = e.currentTarget;
                    const val = input.value.trim();
                    if (val && !phaseForm.required_capabilities.includes(val)) {
                      setPhaseForm({
                        ...phaseForm,
                        required_capabilities: [...phaseForm.required_capabilities, val],
                      });
                      input.value = "";
                    }
                  }
                }}
              />
            </div>
            {/* Auto-complete suggestions from existing agent skills */}
            {(() => {
              const allSkills = new Set(agents.flatMap((a) => a.skills));
              const unused = [...allSkills].filter(
                (s) => !phaseForm.required_capabilities.includes(s)
              );
              if (unused.length === 0) return null;
              return (
                <div className="mt-2">
                  <span className="text-xs text-gray-400">Available skills: </span>
                  <div className="flex flex-wrap gap-1 mt-1">
                    {unused.map((skill) => (
                      <button
                        key={skill}
                        type="button"
                        onClick={() => {
                          setPhaseForm({
                            ...phaseForm,
                            required_capabilities: [...phaseForm.required_capabilities, skill],
                          });
                        }}
                        className="text-xs px-2 py-0.5 rounded bg-gray-100 text-gray-600 hover:bg-gray-200 border border-gray-200"
                      >
                        + {skill}
                      </button>
                    ))}
                  </div>
                </div>
              );
            })()}
          </fieldset>

          {/* Transitions */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                On Success (phase ID)
              </label>
              <select
                value={phaseForm.on_success}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, on_success: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                <option value="">-- None --</option>
                {phases
                  .filter((p) => p.id !== phaseForm.id)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || p.id}
                    </option>
                  ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                On Failure (phase ID)
              </label>
              <select
                value={phaseForm.on_failure}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, on_failure: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                <option value="">-- None --</option>
                {phases
                  .filter((p) => p.id !== phaseForm.id)
                  .map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name || p.id}
                    </option>
                  ))}
              </select>
            </div>
          </div>

          {/* Quality Gates */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Quality Gates
            </legend>
            {phaseForm.quality_gates.length > 0 && (
              <div className="space-y-2 mb-3">
                {phaseForm.quality_gates.map((gate, gi) => (
                  <div
                    key={gi}
                    className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm"
                  >
                    <span>{gate.name}</span>
                    <button
                      onClick={() => removeQualityGate(gi)}
                      className="text-red-500 hover:text-red-700 text-xs"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={newGateName}
                onChange={(e) => setNewGateName(e.target.value)}
                placeholder="Gate name"
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
              />
              <button
                type="button"
                onClick={addQualityGate}
                className="px-3 py-2 bg-gray-200 text-gray-700 rounded-md text-sm hover:bg-gray-300"
              >
                Add Gate
              </button>
            </div>
          </fieldset>

          {/* Toggles */}
          <div className="flex flex-wrap gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={phaseForm.is_terminal}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, is_terminal: e.target.checked })
                }
                className="rounded"
              />
              Terminal
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={phaseForm.requires_human}
                onChange={(e) =>
                  setPhaseForm({
                    ...phaseForm,
                    requires_human: e.target.checked,
                  })
                }
                className="rounded"
              />
              Requires Human
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={phaseForm.parallel}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, parallel: e.target.checked })
                }
                className="rounded"
              />
              Parallel
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={phaseForm.skippable}
                onChange={(e) =>
                  setPhaseForm({ ...phaseForm, skippable: e.target.checked })
                }
                className="rounded"
              />
              Skippable
            </label>
          </div>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setPhaseModalOpen(false)}
              className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSavePhase}
              disabled={loading || !phaseForm.id.trim() || !phaseForm.name.trim()}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Phase"}
            </button>
          </div>
        </div>
      </Modal>

      {/* STATUS MODAL */}
      <Modal
        open={statusModalOpen}
        onClose={() => setStatusModalOpen(false)}
        title={statusEditIdx !== null ? "Edit Status" : "Add Status"}
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ID
              </label>
              <input
                type="text"
                value={statusForm.id}
                onChange={(e) =>
                  setStatusForm({ ...statusForm, id: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                disabled={statusEditIdx !== null}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <input
                type="text"
                value={statusForm.name}
                onChange={(e) =>
                  setStatusForm({ ...statusForm, name: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              />
            </div>
          </div>

          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <input
              type="text"
              value={statusForm.description}
              onChange={(e) =>
                setStatusForm({ ...statusForm, description: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>

          <div className="flex gap-6">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={statusForm.is_initial}
                onChange={(e) =>
                  setStatusForm({
                    ...statusForm,
                    is_initial: e.target.checked,
                  })
                }
                className="rounded"
              />
              Initial
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={statusForm.is_terminal}
                onChange={(e) =>
                  setStatusForm({
                    ...statusForm,
                    is_terminal: e.target.checked,
                  })
                }
                className="rounded"
              />
              Terminal
            </label>
          </div>

          {/* Transitions multi-select */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Transitions To
            </label>
            {statuses.length === 0 ? (
              <p className="text-sm text-gray-400">No other statuses.</p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {statuses
                  .filter((s) => s.id !== statusForm.id)
                  .map((s) => {
                    const selected = statusForm.transitions_to.includes(s.id);
                    return (
                      <button
                        key={s.id}
                        type="button"
                        onClick={() => toggleStatusTransition(s.id)}
                        className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                          selected
                            ? "bg-indigo-100 border-indigo-400 text-indigo-700"
                            : "bg-gray-50 border-gray-300 text-gray-600 hover:bg-gray-100"
                        }`}
                      >
                        {s.name || s.id}
                      </button>
                    );
                  })}
              </div>
            )}
          </div>

          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setStatusModalOpen(false)}
              className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSaveStatus}
              disabled={loading || !statusForm.id.trim() || !statusForm.name.trim()}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Status"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
