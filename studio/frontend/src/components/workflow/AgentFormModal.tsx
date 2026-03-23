import { useState, useEffect, useCallback } from "react";
import { Modal } from "../common/Modal";
import * as api from "../../api/client";
import type { AgentSpec, LLMSpec, RetryPolicySpec, PhaseSpec } from "../../types";
import type { ProviderInfo, ModelInfo } from "../../api/client";

/** Convert a display name to a kebab-case ID slug */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

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

export function emptyAgent(): AgentSpec {
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

interface AgentFormModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly onSave: (agent: AgentSpec) => void;
  readonly initialAgent?: AgentSpec;
  readonly isEdit: boolean;
  readonly loading: boolean;
  readonly phases: readonly PhaseSpec[];
  readonly existingIds: readonly string[];
}

export function AgentFormModal({
  open,
  onClose,
  onSave,
  initialAgent,
  isEdit,
  loading,
  phases,
  existingIds,
}: AgentFormModalProps) {
  const [form, setForm] = useState<AgentSpec>(initialAgent ?? emptyAgent());
  const [manualId, setManualId] = useState(false);
  const [skillsRaw, setSkillsRaw] = useState(
    initialAgent?.skills.join(", ") ?? ""
  );

  const [configuredProviders, setConfiguredProviders] = useState<
    readonly ProviderInfo[]
  >([]);
  const [models, setModels] = useState<readonly ModelInfo[]>([]);
  const [modelsLoading, setModelsLoading] = useState(false);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // Reset form when initialAgent changes
  useEffect(() => {
    if (open) {
      const agent = initialAgent ?? emptyAgent();
      setForm(agent);
      setSkillsRaw(agent.skills.join(", "));
      setManualId(isEdit); // only manual when editing existing
    }
  }, [open, initialAgent, isEdit]);

  /** Generate a unique ID from the name, appending a suffix if needed */
  function generateId(name: string): string {
    const base = slugify(name);
    if (!base) return "";
    if (!existingIds.includes(base)) return base;
    for (let i = 2; i < 100; i++) {
      const candidate = `${base}-${i}`;
      if (!existingIds.includes(candidate)) return candidate;
    }
    return `${base}-${Date.now()}`;
  }

  function handleNameChange(name: string) {
    if (manualId) {
      setForm({ ...form, name });
    } else {
      setForm({ ...form, name, id: generateId(name) });
    }
  }

  // Load configured providers on mount
  useEffect(() => {
    api.getSettings().then(
      (data) => {
        const available = data.providers.filter((p) => p.has_key);
        setConfiguredProviders(available);
      },
      () => {
        /* settings not available */
      }
    );
  }, []);

  const fetchModelsForProvider = useCallback(
    async (providerId: string) => {
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
    },
    []
  );

  // Fetch models when provider changes
  useEffect(() => {
    if (open && form.llm.provider) {
      void fetchModelsForProvider(form.llm.provider);
    }
  }, [open, form.llm.provider, fetchModelsForProvider]);

  function handleProviderChange(providerId: string) {
    setForm({
      ...form,
      llm: { ...form.llm, provider: providerId, model: "" },
    });
  }

  function togglePhase(phaseId: string) {
    const current = [...form.phases];
    const idx = current.indexOf(phaseId);
    if (idx >= 0) current.splice(idx, 1);
    else current.push(phaseId);
    setForm({ ...form, phases: current });
  }

  function handleSave() {
    const parsedSkills = skillsRaw
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    onSave({ ...form, skills: parsedSkills });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit Agent" : "Create Agent"}
      wide
    >
      <div className="space-y-4">
        {/* Name (primary) and ID (auto-derived) */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">
            Name
          </label>
          <input
            type="text"
            value={form.name}
            onChange={(e) => handleNameChange(e.target.value)}
            className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            placeholder="e.g. Research Analyst"
            autoFocus={!isEdit}
          />
          {form.id && (
            <p className="text-xs text-gray-400 mt-1">
              ID: <span className="font-mono">{form.id}</span>
              {!isEdit && !manualId && (
                <button
                  type="button"
                  onClick={() => setManualId(true)}
                  className="ml-2 text-indigo-500 hover:text-indigo-700"
                >
                  edit
                </button>
              )}
            </p>
          )}
          {manualId && !isEdit && (
            <input
              type="text"
              value={form.id}
              onChange={(e) => setForm({ ...form, id: e.target.value })}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mt-1"
              placeholder="custom-agent-id"
            />
          )}
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
                {!configuredProviders.some(
                  (p) => p.id === form.llm.provider
                ) &&
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
                <p className="text-sm text-gray-400 py-2">
                  Loading models...
                </p>
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

        {/* Concurrency & Enabled */}
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
                      backoff_multiplier:
                        parseFloat(e.target.value) || 1,
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
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={loading || !form.id.trim() || !form.name.trim()}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Saving..." : isEdit ? "Save Agent" : "Create Agent"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
