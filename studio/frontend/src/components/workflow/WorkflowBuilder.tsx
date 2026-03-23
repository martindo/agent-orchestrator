import { useState, useCallback, useMemo, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  type Node,
  type Edge,
  type NodeTypes,
  type EdgeTypes,
  type OnNodesChange,
  type OnEdgesChange,
  type Connection,
  applyNodeChanges,
  applyEdgeChanges,
  type NodeChange,
  type EdgeChange,
  type ReactFlowInstance,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import { useTeamStore } from "../../store/teamStore";
import {
  BuilderPhaseNode,
  type BuilderPhaseNodeData,
} from "./nodes/BuilderPhaseNode";
import { TransitionEdge } from "./edges/TransitionEdge";
import { ContextMenu, type MenuItem } from "./ContextMenu";
import { AgentPalette } from "./AgentPalette";
import { PhaseFormModal } from "./PhaseFormModal";
import { AgentFormModal, emptyAgent } from "./AgentFormModal";
import type { PhaseSpec, AgentSpec } from "../../types";

const nodeTypes: NodeTypes = { builderPhase: BuilderPhaseNode };
const edgeTypes: EdgeTypes = { transition: TransitionEdge };

const STORAGE_KEY_PREFIX = "workflow-builder-positions-";

function loadPositions(teamName: string): Record<string, { x: number; y: number }> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY_PREFIX + teamName);
    if (raw) {
      return JSON.parse(raw) as Record<string, { x: number; y: number }>;
    }
  } catch {
    // ignore parse errors
  }
  return {};
}

function savePositions(
  teamName: string,
  positions: Record<string, { x: number; y: number }>
) {
  localStorage.setItem(STORAGE_KEY_PREFIX + teamName, JSON.stringify(positions));
}

function emptyPhase(order: number): PhaseSpec {
  return {
    id: "",
    name: "",
    description: "",
    order,
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

export function WorkflowBuilder() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const addPhase = useTeamStore((s) => s.addPhase);
  const updatePhase = useTeamStore((s) => s.updatePhase);
  const removePhase = useTeamStore((s) => s.removePhase);
  const addAgent = useTeamStore((s) => s.addAgent);
  const updateAgent = useTeamStore((s) => s.updateAgent);
  const removeAgent = useTeamStore((s) => s.removeAgent);

  const agents = team?.agents ?? [];
  const phases = team?.workflow.phases ?? [];
  const teamName = team?.name ?? "";

  const agentNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const a of agents) {
      map[a.id] = a.name || a.id;
    }
    return map;
  }, [agents]);

  // ReactFlow instance ref for coordinate conversions
  const reactFlowInstance = useRef<ReactFlowInstance | null>(null);

  // Phase form modal state
  const [phaseModalOpen, setPhaseModalOpen] = useState(false);
  const [phaseEditIdx, setPhaseEditIdx] = useState<number | null>(null);
  const [phaseForm, setPhaseForm] = useState<PhaseSpec>(emptyPhase(0));

  // Agent form modal state
  const [agentModalOpen, setAgentModalOpen] = useState(false);
  const [agentEditIdx, setAgentEditIdx] = useState<number | null>(null);
  const [agentInitial, setAgentInitial] = useState<AgentSpec | undefined>(
    undefined
  );
  // Optional: when creating agent from a phase node context, auto-assign to that phase
  const [agentTargetPhaseId, setAgentTargetPhaseId] = useState<string | null>(
    null
  );

  // Delete confirmation for agents in palette
  const [agentDeleteConfirm, setAgentDeleteConfirm] = useState<number | null>(
    null
  );

  // Context menu state
  const [contextMenu, setContextMenu] = useState<{
    x: number;
    y: number;
    items: MenuItem[];
  } | null>(null);

  // Build nodes from phases
  const storedPositions = useMemo(
    () => loadPositions(teamName),
    [teamName, phases]
  );

  const nodes = useMemo<Node<BuilderPhaseNodeData>[]>(() => {
    const sorted = [...phases].sort((a, b) => a.order - b.order);
    return sorted.map((p, i) => ({
      id: p.id,
      type: "builderPhase" as const,
      position: storedPositions[p.id] ?? { x: 250, y: i * 160 },
      data: {
        label: p.name || p.id,
        isTerminal: p.is_terminal,
        requiresHuman: p.requires_human,
        agents: [...p.agents],
        agentNames: agentNameMap,
      },
    }));
  }, [phases, storedPositions, agentNameMap]);

  // Build edges from phase transitions
  const edges = useMemo<Edge[]>(() => {
    const result: Edge[] = [];
    for (const p of phases) {
      if (p.on_success) {
        result.push({
          id: `${p.id}-success-${p.on_success}`,
          source: p.id,
          target: p.on_success,
          sourceHandle: "success",
          type: "transition",
        });
      }
      if (p.on_failure && p.on_failure !== p.on_success) {
        result.push({
          id: `${p.id}-failure-${p.on_failure}`,
          source: p.id,
          target: p.on_failure,
          sourceHandle: "failure",
          type: "transition",
        });
      }
    }
    return result;
  }, [phases]);

  // Tracked node/edge state for selection + dragging
  const [currentNodes, setCurrentNodes] = useState<Node[]>([]);
  const [currentEdges, setCurrentEdges] = useState<Edge[]>([]);

  // Sync when data changes
  useMemo(() => {
    setCurrentNodes(nodes);
  }, [nodes]);
  useMemo(() => {
    setCurrentEdges(edges);
  }, [edges]);

  const onNodesChange: OnNodesChange = useCallback(
    (changes: NodeChange[]) => {
      setCurrentNodes((nds) => {
        const updated = applyNodeChanges(changes, nds);
        // Save positions on drag
        for (const change of changes) {
          if (change.type === "position" && change.position && teamName) {
            const positions = loadPositions(teamName);
            positions[change.id] = change.position;
            savePositions(teamName, positions);
          }
        }
        return updated;
      });
    },
    [teamName]
  );

  const onEdgesChange: OnEdgesChange = useCallback(
    (changes: EdgeChange[]) => {
      setCurrentEdges((eds) => applyEdgeChanges(changes, eds));
    },
    []
  );

  // Handle new connections (drag handle-to-handle)
  const onConnect = useCallback(
    (connection: Connection) => {
      const sourcePhaseIdx = phases.findIndex(
        (p) => p.id === connection.source
      );
      if (sourcePhaseIdx < 0) return;

      const sourcePhase = phases[sourcePhaseIdx];
      if (!sourcePhase || !connection.target) return;

      const isSuccess = connection.sourceHandle === "success";
      const updatedPhase: PhaseSpec = {
        ...sourcePhase,
        ...(isSuccess
          ? { on_success: connection.target }
          : { on_failure: connection.target }),
      };

      void updatePhase(sourcePhaseIdx, updatedPhase);
    },
    [phases, updatePhase]
  );

  // Delete key handler
  const onKeyDown = useCallback(
    (event: React.KeyboardEvent) => {
      if (event.key !== "Delete" && event.key !== "Backspace") return;

      // Don't intercept if user is typing in an input
      const tag = (event.target as HTMLElement).tagName;
      if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;

      // Delete selected edges first (remove transitions)
      for (const edge of currentEdges) {
        if (!edge.selected) continue;
        const phaseIdx = phases.findIndex((p) => p.id === edge.source);
        if (phaseIdx < 0) continue;
        const phase = phases[phaseIdx];
        if (!phase) continue;
        const isSuccess = edge.sourceHandle === "success";
        void updatePhase(phaseIdx, {
          ...phase,
          ...(isSuccess ? { on_success: "" } : { on_failure: "" }),
        });
      }

      // Delete selected nodes
      for (const node of currentNodes) {
        if (!node.selected) continue;
        const phaseIdx = phases.findIndex((p) => p.id === node.id);
        if (phaseIdx >= 0) {
          void removePhase(phaseIdx);
        }
      }
    },
    [currentNodes, currentEdges, phases, updatePhase, removePhase]
  );

  // Node double-click -> open edit modal
  const onNodeDoubleClick = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      const idx = phases.findIndex((p) => p.id === node.id);
      if (idx < 0) return;
      const p = phases[idx];
      if (!p) return;
      setPhaseForm(p);
      setPhaseEditIdx(idx);
      setPhaseModalOpen(true);
    },
    [phases]
  );

  // --- Agent modal helpers ---
  function openCreateAgent(targetPhaseId?: string) {
    setAgentInitial(undefined);
    setAgentEditIdx(null);
    setAgentTargetPhaseId(targetPhaseId ?? null);
    setAgentModalOpen(true);
  }

  function openEditAgent(index: number) {
    const agent = agents[index];
    if (!agent) return;
    setAgentInitial(agent);
    setAgentEditIdx(index);
    setAgentTargetPhaseId(null);
    setAgentModalOpen(true);
  }

  function handleDeleteAgent(index: number) {
    if (agentDeleteConfirm === index) {
      void removeAgent(index);
      setAgentDeleteConfirm(null);
    } else {
      setAgentDeleteConfirm(index);
      // Auto-clear after 3 seconds
      setTimeout(() => setAgentDeleteConfirm(null), 3000);
    }
  }

  function handleSaveAgent(agent: AgentSpec) {
    if (agentEditIdx !== null) {
      void updateAgent(agentEditIdx, agent);
    } else {
      void addAgent(agent);
      // If creating from a phase node, also assign the agent to that phase
      if (agentTargetPhaseId) {
        const phaseIdx = phases.findIndex(
          (p) => p.id === agentTargetPhaseId
        );
        if (phaseIdx >= 0) {
          const phase = phases[phaseIdx];
          if (phase && !phase.agents.includes(agent.id)) {
            void updatePhase(phaseIdx, {
              ...phase,
              agents: [...phase.agents, agent.id],
            });
          }
        }
      }
    }
    setAgentModalOpen(false);
    setAgentTargetPhaseId(null);
  }

  // --- Context menu handlers ---
  const onNodeContextMenu = useCallback(
    (event: React.MouseEvent, node: Node) => {
      event.preventDefault();
      const idx = phases.findIndex((p) => p.id === node.id);
      if (idx < 0) return;
      const phase = phases[idx];
      if (!phase) return;

      // Build "Add Agent" submenu items
      const unassignedAgents = agents.filter(
        (a) => !phase.agents.includes(a.id)
      );

      const items: MenuItem[] = [
        {
          label: "Edit Phase",
          onClick: () => {
            setPhaseForm(phase);
            setPhaseEditIdx(idx);
            setPhaseModalOpen(true);
          },
        },
        {
          label: phase.is_terminal ? "Unset Terminal" : "Set Terminal",
          onClick: () => {
            void updatePhase(idx, {
              ...phase,
              is_terminal: !phase.is_terminal,
            });
          },
        },
        {
          label: phase.requires_human
            ? "Unset Requires Human"
            : "Set Requires Human",
          onClick: () => {
            void updatePhase(idx, {
              ...phase,
              requires_human: !phase.requires_human,
            });
          },
        },
      ];

      // Add existing agents to this phase
      if (unassignedAgents.length > 0) {
        items.push({
          label: "--- Assign Agent ---",
          onClick: () => {},
          divider: true,
        });
        for (const agent of unassignedAgents) {
          items.push({
            label: `+ ${agent.name || agent.id}`,
            onClick: () => {
              void updatePhase(idx, {
                ...phase,
                agents: [...phase.agents, agent.id],
              });
            },
          });
        }
      }

      // Remove assigned agents from this phase
      if (phase.agents.length > 0) {
        items.push({
          label: "--- Remove Agent ---",
          onClick: () => {},
          divider: true,
        });
        for (const agentId of phase.agents) {
          const agentName = agentNameMap[agentId] ?? agentId;
          items.push({
            label: `- ${agentName}`,
            onClick: () => {
              void updatePhase(idx, {
                ...phase,
                agents: phase.agents.filter((a) => a !== agentId),
              });
            },
            danger: true,
          });
        }
      }

      items.push({
        label: "Create New Agent for Phase",
        onClick: () => openCreateAgent(phase.id),
        divider: true,
      });

      items.push({
        label: "Delete Phase",
        onClick: () => void removePhase(idx),
        danger: true,
        divider: true,
      });

      setContextMenu({ x: event.clientX, y: event.clientY, items });
    },
    [phases, agents, agentNameMap, updatePhase, removePhase]
  );

  const onEdgeContextMenu = useCallback(
    (event: React.MouseEvent, edge: Edge) => {
      event.preventDefault();
      const phaseIdx = phases.findIndex((p) => p.id === edge.source);
      if (phaseIdx < 0) return;
      const phase = phases[phaseIdx];
      if (!phase) return;

      const isSuccess = edge.sourceHandle === "success";
      const items: MenuItem[] = [
        {
          label: `Switch to ${isSuccess ? "Failure" : "Success"}`,
          onClick: () => {
            void updatePhase(phaseIdx, {
              ...phase,
              on_success: isSuccess ? "" : edge.target,
              on_failure: isSuccess ? edge.target : "",
            });
          },
        },
        {
          label: "Remove Transition",
          onClick: () => {
            void updatePhase(phaseIdx, {
              ...phase,
              ...(isSuccess ? { on_success: "" } : { on_failure: "" }),
            });
          },
          danger: true,
          divider: true,
        },
      ];

      setContextMenu({ x: event.clientX, y: event.clientY, items });
    },
    [phases, updatePhase]
  );

  const onPaneContextMenu = useCallback(
    (event: MouseEvent | React.MouseEvent) => {
      event.preventDefault();

      const flowPosition = reactFlowInstance.current?.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      const items: MenuItem[] = [
        {
          label: "Add New Phase Here",
          onClick: () => {
            const newPhase = emptyPhase(phases.length);
            setPhaseForm(newPhase);
            setPhaseEditIdx(null);
            setPhaseModalOpen(true);

            if (flowPosition && teamName) {
              sessionStorage.setItem(
                "pending-phase-position",
                JSON.stringify(flowPosition)
              );
            }
          },
        },
        {
          label: "Create New Agent",
          onClick: () => openCreateAgent(),
          divider: true,
        },
      ];

      setContextMenu({
        x: event.clientX,
        y: event.clientY,
        items,
      });
    },
    [phases.length, teamName]
  );

  // Handle saving phase from modal
  function handleSavePhase() {
    if (phaseEditIdx !== null) {
      void updatePhase(phaseEditIdx, phaseForm);
    } else {
      void addPhase(phaseForm);
      // Apply pending position if set
      const pendingPos = sessionStorage.getItem("pending-phase-position");
      if (pendingPos && teamName && phaseForm.id) {
        try {
          const pos = JSON.parse(pendingPos) as { x: number; y: number };
          const positions = loadPositions(teamName);
          positions[phaseForm.id] = pos;
          savePositions(teamName, positions);
        } catch {
          // ignore
        }
        sessionStorage.removeItem("pending-phase-position");
      }
    }
    setPhaseModalOpen(false);
  }

  // Handle agent drop onto a phase node
  const onDragOver = useCallback((event: React.DragEvent) => {
    event.preventDefault();
    event.dataTransfer.dropEffect = "copy";
  }, []);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const agentId = event.dataTransfer.getData("application/agent-id");
      if (!agentId || !reactFlowInstance.current) return;

      // Find which node the drop landed on
      const flowPos = reactFlowInstance.current.screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      });

      // Check if drop is over a node
      const targetNode = currentNodes.find((n) => {
        const nx = n.position.x;
        const ny = n.position.y;
        // Approximate node bounds (180x80)
        return (
          flowPos.x >= nx - 10 &&
          flowPos.x <= nx + 190 &&
          flowPos.y >= ny - 10 &&
          flowPos.y <= ny + 90
        );
      });

      if (!targetNode) return;

      const phaseIdx = phases.findIndex((p) => p.id === targetNode.id);
      if (phaseIdx < 0) return;
      const phase = phases[phaseIdx];
      if (!phase) return;

      // Don't add duplicate
      if (phase.agents.includes(agentId)) return;

      void updatePhase(phaseIdx, {
        ...phase,
        agents: [...phase.agents, agentId],
      });
    },
    [currentNodes, phases, updatePhase]
  );

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  return (
    <div className="flex bg-white rounded-lg shadow" style={{ height: 600 }}>
      {/* Agent Palette Sidebar */}
      <AgentPalette
        agents={agents}
        onCreateAgent={() => openCreateAgent()}
        onEditAgent={(i) => openEditAgent(i)}
        onDeleteAgent={(i) => handleDeleteAgent(i)}
      />

      {/* ReactFlow Canvas — always rendered so right-click works */}
      <div
        className="flex-1 relative"
        onKeyDown={onKeyDown}
        tabIndex={0}
      >
        <ReactFlow
          nodes={currentNodes}
          edges={currentEdges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          onNodeDoubleClick={onNodeDoubleClick}
          onNodeContextMenu={onNodeContextMenu}
          onEdgeContextMenu={onEdgeContextMenu}
          onPaneContextMenu={onPaneContextMenu}
          onDragOver={onDragOver}
          onDrop={onDrop}
          onInit={(instance) => {
            reactFlowInstance.current = instance;
          }}
          fitView
          deleteKeyCode={null}
          proOptions={{ hideAttribution: true }}
          defaultEdgeOptions={{ type: "transition" }}
        >
          <Background />
          <Controls />
          {currentNodes.length > 0 && (
            <MiniMap
              nodeColor={(node) => {
                const data = node.data as BuilderPhaseNodeData;
                if (data.isTerminal) return "#fca5a5";
                if (data.requiresHuman) return "#fde68a";
                return "#c7d2fe";
              }}
            />
          )}
        </ReactFlow>


        {/* Context Menu */}
        {contextMenu && (
          <ContextMenu
            x={contextMenu.x}
            y={contextMenu.y}
            items={contextMenu.items}
            onClose={() => setContextMenu(null)}
          />
        )}
      </div>

      {/* Phase Edit Modal */}
      <PhaseFormModal
        open={phaseModalOpen}
        onClose={() => setPhaseModalOpen(false)}
        phase={phaseForm}
        onChange={setPhaseForm}
        onSave={handleSavePhase}
        isEdit={phaseEditIdx !== null}
        loading={loading}
        agents={agents}
        phases={phases}
      />

      {/* Agent Create/Edit Modal */}
      <AgentFormModal
        open={agentModalOpen}
        onClose={() => {
          setAgentModalOpen(false);
          setAgentTargetPhaseId(null);
        }}
        onSave={handleSaveAgent}
        initialAgent={agentInitial}
        isEdit={agentEditIdx !== null}
        loading={loading}
        phases={phases}
        existingIds={agents.map((a) => a.id)}
      />
    </div>
  );
}
