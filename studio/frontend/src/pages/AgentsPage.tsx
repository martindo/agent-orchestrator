import { useState, useEffect, useCallback } from "react";
import { useTeamStore } from "../store/teamStore";
import { Modal } from "../components/common/Modal";
import * as api from "../api/client";
import type { AgentSpec, LLMSpec, RetryPolicySpec } from "../types";
import type { ProviderInfo, ModelInfo } from "../api/client";

function defaultLLM(): LLMSpec {
  return {
    provider: "openai",
    model: "gpt-4o",
    temperature: 0.7,
    max_tokens: 4096,
    endpoint: null,
  };
}

function defaultRetry(): RetryPolicySpec {
  return {
    max_retries: 3,
    delay_seconds: 1,
    backoff_multiplier: 2,
  };
}

function emptyAgent(): AgentSpec {
  return {
    id: "",
    name: "",
    description: "",
    system_prompt: "",
    skills: [],
    phases: [],
    llm: defaultLLM(),
    concurrency: 1,
    retry_policy: defaultRetry(),
    enabled: true,
  };
}

export function AgentsPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const addAgent = useTeamStore((s) => s.addAgent);
  const updateAgent = useTeamStore((s) => s.updateAgent);
  const removeAgent = useTeamStore((s) => s.removeAgent);

  const [modalOpen, setModalOpen] = useState(false);
  const [editIndex, setEditIndex] = useState<number | null>(null);
  const [form, setForm] = useState<AgentSpec>(emptyAgent());
  const [skillsRaw, setSkillsRaw] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  // Provider/model state from settings API
  const [configuredProviders, setConfiguredProviders] = useState<readonly ProviderInfo[]>([]);
  const [models, setModels] = useState<readonly ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const phases = team?.workflow.phases ?? [];

  // Load configured providers on mount
  useEffect(() => {
    api.getSettings().then(
      (data) => {
        const available = data.providers.filter((p) => p.has_key);
        setConfiguredProviders(available);
      },
      () => { /* settings not available */ },
    );
  }, []);

  // Fetch models when provider changes in the form
  const fetchModelsForProvider = useCallback(async (providerId: string) => {
    if (!providerId) return;
    setModelsLoading(true);
    setModelsError(null);
    setModels([]);
    try {
      const result = await api.fetchModels(providerId);
      setModels(result.models);
      if (result.error) {
        setModelsError(result.error);
      }
    } catch (e) {
      setModelsError(String(e));
    } finally {
      setModelsLoading(false);
    }
  }, []);

  function openAdd() {
    const agent = emptyAgent();
    // Default to first configured provider
    const firstProvider = configuredProviders.length > 0 ? configuredProviders[0] : undefined;
    if (firstProvider) {
      const llm: LLMSpec = { ...agent.llm, provider: firstProvider.id, model: "" };
      setForm({ ...agent, llm });
      void fetchModelsForProvider(firstProvider.id);
    } else {
      setForm(agent);
    }
    setSkillsRaw("");
    setEditIndex(null);
    setModalOpen(true);
  }

  function openEdit(index: number) {
    const agent = team?.agents[index];
    if (!agent) return;
    setForm(agent);
    setSkillsRaw(agent.skills.join(", "));
    setEditIndex(index);
    setModalOpen(true);
    void fetchModelsForProvider(agent.llm.provider);
  }

  function handleProviderChange(providerId: string) {
    setForm({
      ...form,
      llm: { ...form.llm, provider: providerId, model: "" },
    });
    void fetchModelsForProvider(providerId);
  }

  function handleSave() {
    const parsedSkills = skillsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    const agent: AgentSpec = { ...form, skills: parsedSkills };

    if (editIndex !== null) {
      void updateAgent(editIndex, agent);
    } else {
      void addAgent(agent);
    }
    setModalOpen(false);
  }

  function handleDelete(index: number) {
    void removeAgent(index);
    setDeleteConfirm(null);
  }

  function togglePhase(phaseId: string) {
    const current = [...form.phases];
    const idx = current.indexOf(phaseId);
    if (idx >= 0) {
      current.splice(idx, 1);
    } else {
      current.push(phaseId);
    }
    setForm({ ...form, phases: current });
  }

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Agents</h2>
        <button
          onClick={openAdd}
          className="bg-indigo-600 text-white px-4 py-2 rounded-md hover:bg-indigo-700 text-sm font-medium"
        >
          + Add Agent
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {team.agents.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No agents defined yet. Click &quot;+ Add Agent&quot; to get started.
        </div>
      ) : (
        <div className="space-y-3">
          {team.agents.map((agent, i) => (
            <div
              key={agent.id}
              className="bg-white rounded-lg shadow p-4 flex items-start justify-between"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-sm">{agent.name}</h3>
                  <span className="text-xs text-gray-400 font-mono">
                    {agent.id}
                  </span>
                  {!agent.enabled && (
                    <span className="text-xs bg-gray-200 text-gray-600 px-2 py-0.5 rounded">
                      disabled
                    </span>
                  )}
                </div>
                <p className="text-sm text-gray-600 mt-1 line-clamp-1">
                  {agent.description || "No description"}
                </p>
                <div className="flex flex-wrap gap-1 mt-2">
                  <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                    {agent.llm.provider}/{agent.llm.model}
                  </span>
                  {agent.skills.map((s) => (
                    <span
                      key={s}
                      className="text-xs bg-green-100 text-green-700 px-2 py-0.5 rounded"
                    >
                      {s}
                    </span>
                  ))}
                  {agent.phases.map((p) => (
                    <span
                      key={p}
                      className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded"
                    >
                      {p}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex gap-2 ml-4 shrink-0">
                <button
                  onClick={() => openEdit(i)}
                  className="text-sm text-indigo-600 hover:text-indigo-800"
                >
                  Edit
                </button>
                {deleteConfirm === i ? (
                  <div className="flex gap-1">
                    <button
                      onClick={() => handleDelete(i)}
                      className="text-sm text-red-600 font-medium"
                    >
                      Confirm
                    </button>
                    <button
                      onClick={() => setDeleteConfirm(null)}
                      className="text-sm text-gray-500"
                    >
                      Cancel
                    </button>
                  </div>
                ) : (
                  <button
                    onClick={() => setDeleteConfirm(i)}
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

      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editIndex !== null ? "Edit Agent" : "Add Agent"}
        wide
      >
        <div className="space-y-4">
          {/* ID and Name */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ID
              </label>
              <input
                type="text"
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="agent-id"
                disabled={editIndex !== null}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <input
                type="text"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="Agent Name"
              />
            </div>
          </div>

          {/* Description */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Description
            </label>
            <input
              type="text"
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>

          {/* System Prompt */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              System Prompt
            </label>
            <textarea
              value={form.system_prompt}
              onChange={(e) =>
                setForm({ ...form, system_prompt: e.target.value })
              }
              rows={4}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
            />
          </div>

          {/* Skills */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Skills (comma-separated)
            </label>
            <input
              type="text"
              value={skillsRaw}
              onChange={(e) => setSkillsRaw(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="analysis, writing, code_review"
            />
          </div>

          {/* Phases multi-select */}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Phases
            </label>
            {phases.length === 0 ? (
              <p className="text-sm text-gray-400">
                No phases defined yet in workflow.
              </p>
            ) : (
              <div className="flex flex-wrap gap-2">
                {phases.map((p) => {
                  const selected = form.phases.includes(p.id);
                  return (
                    <button
                      key={p.id}
                      type="button"
                      onClick={() => togglePhase(p.id)}
                      className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                        selected
                          ? "bg-indigo-100 border-indigo-400 text-indigo-700"
                          : "bg-gray-50 border-gray-300 text-gray-600 hover:bg-gray-100"
                      }`}
                    >
                      {p.name || p.id}
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          {/* LLM Config */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              LLM Configuration
            </legend>

            {configuredProviders.length === 0 && (
              <p className="text-sm text-amber-600 mb-3">
                No LLM providers configured. Go to Settings to add API keys.
              </p>
            )}

            <div className="grid grid-cols-2 gap-4 mt-2">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Provider
                </label>
                <select
                  value={form.llm.provider}
                  onChange={(e) => handleProviderChange(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                >
                  {/* Show current provider even if not configured (for editing existing agents) */}
                  {!configuredProviders.some((p) => p.id === form.llm.provider) &&
                    form.llm.provider && (
                      <option value={form.llm.provider}>
                        {form.llm.provider} (key not set)
                      </option>
                    )}
                  {configuredProviders.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Model
                </label>
                {modelsLoading ? (
                  <p className="text-sm text-gray-400 py-2">Loading models...</p>
                ) : models.length > 0 ? (
                  <select
                    value={form.llm.model}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        llm: { ...form.llm, model: e.target.value },
                      })
                    }
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  >
                    {/* Keep current model as option if not in fetched list */}
                    {form.llm.model &&
                      !models.some((m) => m.id === form.llm.model) && (
                        <option value={form.llm.model}>
                          {form.llm.model} (current)
                        </option>
                      )}
                    <option value="">-- Select model --</option>
                    {models.map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.name !== m.id ? `${m.name} (${m.id})` : m.id}
                      </option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={form.llm.model}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        llm: { ...form.llm, model: e.target.value },
                      })
                    }
                    className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                    placeholder="Enter model ID"
                  />
                )}
                {modelsError && (
                  <p className="text-xs text-red-500 mt-1">{modelsError}</p>
                )}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 mt-3">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Temperature: {form.llm.temperature.toFixed(2)}
                </label>
                <input
                  type="range"
                  min="0"
                  max="2"
                  step="0.01"
                  value={form.llm.temperature}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      llm: {
                        ...form.llm,
                        temperature: parseFloat(e.target.value),
                      },
                    })
                  }
                  className="w-full"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Max Tokens
                </label>
                <input
                  type="number"
                  value={form.llm.max_tokens}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      llm: {
                        ...form.llm,
                        max_tokens: parseInt(e.target.value, 10) || 0,
                      },
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  min={1}
                />
              </div>
            </div>
          </fieldset>

          {/* Concurrency & Retry */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Concurrency
              </label>
              <input
                type="number"
                value={form.concurrency}
                onChange={(e) =>
                  setForm({
                    ...form,
                    concurrency: parseInt(e.target.value, 10) || 1,
                  })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                min={1}
              />
            </div>
            <div>
              <label className="flex items-center gap-2 text-sm font-medium text-gray-700 mt-6">
                <input
                  type="checkbox"
                  checked={form.enabled}
                  onChange={(e) =>
                    setForm({ ...form, enabled: e.target.checked })
                  }
                  className="rounded"
                />
                Enabled
              </label>
            </div>
          </div>

          {/* Retry Policy */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Retry Policy
            </legend>
            <div className="grid grid-cols-3 gap-4 mt-2">
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Max Retries
                </label>
                <input
                  type="number"
                  value={form.retry_policy.max_retries}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      retry_policy: {
                        ...form.retry_policy,
                        max_retries: parseInt(e.target.value, 10) || 0,
                      },
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  min={0}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Delay (s)
                </label>
                <input
                  type="number"
                  value={form.retry_policy.delay_seconds}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      retry_policy: {
                        ...form.retry_policy,
                        delay_seconds: parseFloat(e.target.value) || 0,
                      },
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  min={0}
                  step={0.5}
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-600 mb-1">
                  Backoff Multiplier
                </label>
                <input
                  type="number"
                  value={form.retry_policy.backoff_multiplier}
                  onChange={(e) =>
                    setForm({
                      ...form,
                      retry_policy: {
                        ...form.retry_policy,
                        backoff_multiplier: parseFloat(e.target.value) || 1,
                      },
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                  min={1}
                  step={0.5}
                />
              </div>
            </div>
          </fieldset>

          {/* Actions */}
          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setModalOpen(false)}
              className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={loading || !form.id.trim() || !form.name.trim()}
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Agent"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
