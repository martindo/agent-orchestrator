/**
 * Zustand store for the current working team.
 * Single source of truth for team state across all editor components.
 */

import { create } from "zustand";
import type {
  TeamSpec,
  AgentSpec,
  PhaseSpec,
  PolicySpec,
  WorkItemTypeSpec,
  StatusSpec,
  ValidationResult,
} from "../types";
import * as api from "../api/client";

type View =
  | "overview"
  | "recommend"
  | "agents"
  | "workflow"
  | "governance"
  | "workitems"
  | "preview"
  | "deploy"
  | "settings";

interface TeamStore {
  // State
  team: TeamSpec | null;
  loading: boolean;
  error: string | null;
  currentView: View;
  validation: ValidationResult | null;
  yamlPreview: Record<string, string> | null;

  // Actions
  setView: (view: View) => void;
  createTeam: (name: string, description?: string) => Promise<void>;
  loadTeam: () => Promise<void>;
  importTemplate: (nameOrPath: string, isPath?: boolean) => Promise<void>;
  updateTeam: (team: TeamSpec) => Promise<void>;

  // Agent actions
  addAgent: (agent: AgentSpec) => Promise<void>;
  updateAgent: (index: number, agent: AgentSpec) => Promise<void>;
  removeAgent: (index: number) => Promise<void>;

  // Phase actions
  addPhase: (phase: PhaseSpec) => Promise<void>;
  updatePhase: (index: number, phase: PhaseSpec) => Promise<void>;
  removePhase: (index: number) => Promise<void>;

  // Status actions
  addStatus: (status: StatusSpec) => Promise<void>;
  updateStatus: (index: number, status: StatusSpec) => Promise<void>;
  removeStatus: (index: number) => Promise<void>;

  // Policy actions
  addPolicy: (policy: PolicySpec) => Promise<void>;
  updatePolicy: (index: number, policy: PolicySpec) => Promise<void>;
  removePolicy: (index: number) => Promise<void>;

  // Work item actions
  addWorkItemType: (wit: WorkItemTypeSpec) => Promise<void>;
  updateWorkItemType: (index: number, wit: WorkItemTypeSpec) => Promise<void>;
  removeWorkItemType: (index: number) => Promise<void>;

  // Bulk add (for recommendations)
  bulkAddAgentsAndPhases: (
    agents: AgentSpec[],
    phases: PhaseSpec[],
    teamName?: string,
    teamDescription?: string,
  ) => Promise<void>;

  // Validation & preview
  validate: () => Promise<void>;
  loadPreview: () => Promise<void>;

  // Deploy
  deployProfile: (options?: {
    profile_name?: string;
    trigger_reload?: boolean;
  }) => Promise<{ success: boolean; errors: string[]; warnings: string[] }>;
}

function mutableTeam(team: TeamSpec): Record<string, unknown> {
  return JSON.parse(JSON.stringify(team));
}

export const useTeamStore = create<TeamStore>((set, get) => ({
  team: null,
  loading: false,
  error: null,
  currentView: "overview",
  validation: null,
  yamlPreview: null,

  setView: (view) => set({ currentView: view }),

  createTeam: async (name, description = "") => {
    set({ loading: true, error: null });
    try {
      const team = await api.createTeam(name, description);
      set({ team, loading: false });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  loadTeam: async () => {
    set({ loading: true, error: null });
    try {
      const team = await api.getCurrentTeam();
      set({ team, loading: false });
    } catch (e) {
      // 404 is expected when no team exists yet — not an error
      const msg = String(e);
      if (msg.includes("404")) {
        set({ loading: false });
      } else {
        set({ error: msg, loading: false });
      }
    }
  },

  importTemplate: async (nameOrPath, isPath = false) => {
    set({ loading: true, error: null });
    try {
      const team = isPath
        ? await api.importTemplate(undefined, nameOrPath)
        : await api.importTemplate(nameOrPath);
      set({ team, loading: false });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  updateTeam: async (team) => {
    set({ loading: true, error: null });
    try {
      const updated = await api.updateCurrentTeam(team);
      set({ team: updated, loading: false, validation: null, yamlPreview: null });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  addAgent: async (agent) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const t = mutableTeam(team) as unknown as { agents: AgentSpec[] } & TeamSpec;
    await updateTeam({ ...team, agents: [...team.agents, agent] });
  },

  updateAgent: async (index, agent) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const agents = [...team.agents];
    agents[index] = agent;
    await updateTeam({ ...team, agents });
  },

  removeAgent: async (index) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const agents = team.agents.filter((_, i) => i !== index);
    await updateTeam({ ...team, agents });
  },

  addPhase: async (phase) => {
    const { team, updateTeam } = get();
    if (!team) return;
    await updateTeam({
      ...team,
      workflow: {
        ...team.workflow,
        phases: [...team.workflow.phases, phase],
      },
    });
  },

  updatePhase: async (index, phase) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const phases = [...team.workflow.phases];
    phases[index] = phase;
    await updateTeam({
      ...team,
      workflow: { ...team.workflow, phases },
    });
  },

  removePhase: async (index) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const phases = team.workflow.phases.filter((_, i) => i !== index);
    await updateTeam({
      ...team,
      workflow: { ...team.workflow, phases },
    });
  },

  addStatus: async (status) => {
    const { team, updateTeam } = get();
    if (!team) return;
    await updateTeam({
      ...team,
      workflow: {
        ...team.workflow,
        statuses: [...team.workflow.statuses, status],
      },
    });
  },

  updateStatus: async (index, status) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const statuses = [...team.workflow.statuses];
    statuses[index] = status;
    await updateTeam({
      ...team,
      workflow: { ...team.workflow, statuses },
    });
  },

  removeStatus: async (index) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const statuses = team.workflow.statuses.filter((_, i) => i !== index);
    await updateTeam({
      ...team,
      workflow: { ...team.workflow, statuses },
    });
  },

  addPolicy: async (policy) => {
    const { team, updateTeam } = get();
    if (!team) return;
    await updateTeam({
      ...team,
      governance: {
        ...team.governance,
        policies: [...team.governance.policies, policy],
      },
    });
  },

  updatePolicy: async (index, policy) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const policies = [...team.governance.policies];
    policies[index] = policy;
    await updateTeam({
      ...team,
      governance: { ...team.governance, policies },
    });
  },

  removePolicy: async (index) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const policies = team.governance.policies.filter((_, i) => i !== index);
    await updateTeam({
      ...team,
      governance: { ...team.governance, policies },
    });
  },

  addWorkItemType: async (wit) => {
    const { team, updateTeam } = get();
    if (!team) return;
    await updateTeam({
      ...team,
      work_item_types: [...team.work_item_types, wit],
    });
  },

  updateWorkItemType: async (index, wit) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const wits = [...team.work_item_types];
    wits[index] = wit;
    await updateTeam({ ...team, work_item_types: wits });
  },

  removeWorkItemType: async (index) => {
    const { team, updateTeam } = get();
    if (!team) return;
    const wits = team.work_item_types.filter((_, i) => i !== index);
    await updateTeam({ ...team, work_item_types: wits });
  },

  bulkAddAgentsAndPhases: async (agents, phases, teamName, teamDescription) => {
    let currentTeam = get().team;
    set({ loading: true, error: null });
    try {
      if (!currentTeam) {
        // Create a new team first (inline, not via createTeam which fights with loading state)
        const created = await api.createTeam(teamName ?? "Recommended Team", teamDescription ?? "");
        set({ team: created });
        currentTeam = created;
      }
      // Deduplicate: check for ID collisions
      const existingAgentIds = new Set(currentTeam.agents.map((a) => a.id));
      const existingPhaseIds = new Set(currentTeam.workflow.phases.map((p) => p.id));

      const resolvedAgents = agents.map((agent) => {
        let id = agent.id;
        let suffix = 2;
        while (existingAgentIds.has(id)) {
          id = `${agent.id}-${suffix}`;
          suffix++;
        }
        existingAgentIds.add(id);
        return id !== agent.id ? { ...agent, id } : agent;
      });

      const resolvedPhases = phases.map((phase) => {
        let id = phase.id;
        let suffix = 2;
        while (existingPhaseIds.has(id)) {
          id = `${phase.id}-${suffix}`;
          suffix++;
          }
          existingPhaseIds.add(id);
          return id !== phase.id ? { ...phase, id } : phase;
        });

      const updated = await api.updateCurrentTeam({
        ...currentTeam,
        agents: [...currentTeam.agents, ...resolvedAgents],
        workflow: {
          ...currentTeam.workflow,
          phases: [...currentTeam.workflow.phases, ...resolvedPhases],
        },
      });
      set({ team: updated, loading: false, validation: null, yamlPreview: null, currentView: "agents" });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  validate: async () => {
    set({ loading: true });
    try {
      const validation = await api.validateTeam();
      set({ validation, loading: false });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  loadPreview: async () => {
    set({ loading: true });
    try {
      const yamlPreview = await api.previewAll();
      set({ yamlPreview, loading: false });
    } catch (e) {
      set({ error: String(e), loading: false });
    }
  },

  deployProfile: async (options = {}) => {
    set({ loading: true });
    try {
      const result = await api.deploy({
        profile_name: options.profile_name,
        trigger_reload: options.trigger_reload ?? true,
        validate_first: true,
      });
      set({ loading: false });
      return { success: result.success, errors: result.errors, warnings: result.warnings };
    } catch (e) {
      set({ error: String(e), loading: false });
      return { success: false, errors: [String(e)], warnings: [] };
    }
  },
}));
