import { useState, useEffect, useCallback } from "react";
import * as api from "../api/client";
import type { ProviderInfo, ModelInfo } from "../api/client";

interface ProviderForm {
  apiKey: string;
  endpoint: string;
  showKey: boolean;
  saving: boolean;
  feedback: { type: "success" | "error"; message: string } | null;
}

interface ModelsState {
  loading: boolean;
  models: readonly ModelInfo[];
  error: string | null;
  loaded: boolean;
}

export function SettingsPage() {
  const [providers, setProviders] = useState<readonly ProviderInfo[]>([]);
  const [forms, setForms] = useState<Record<string, ProviderForm>>({});
  const [modelsMap, setModelsMap] = useState<Record<string, ModelsState>>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    try {
      const data = await api.getSettings();
      setProviders(data.providers);
      const initial: Record<string, ProviderForm> = {};
      for (const p of data.providers) {
        initial[p.id] = {
          apiKey: "",
          endpoint: p.endpoint,
          showKey: false,
          saving: false,
          feedback: null,
        };
      }
      setForms(initial);
      setError(null);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadSettings();
  }, [loadSettings]);

  function updateForm(providerId: string, patch: Partial<ProviderForm>) {
    setForms((prev) => {
      const existing = prev[providerId];
      if (!existing) return prev;
      const updated: ProviderForm = {
        apiKey: patch.apiKey ?? existing.apiKey,
        endpoint: patch.endpoint ?? existing.endpoint,
        showKey: patch.showKey ?? existing.showKey,
        saving: patch.saving ?? existing.saving,
        feedback: "feedback" in patch ? (patch.feedback ?? null) : existing.feedback,
      };
      return { ...prev, [providerId]: updated };
    });
  }

  async function saveKey(providerId: string) {
    const form = forms[providerId];
    if (!form) return;

    updateForm(providerId, { saving: true, feedback: null });

    try {
      const updates: { api_keys?: Record<string, string>; endpoints?: Record<string, string> } = {};

      if (form.apiKey) {
        updates.api_keys = { [providerId]: form.apiKey };
      }

      const provider = providers.find((p) => p.id === providerId);
      if (form.endpoint !== (provider?.endpoint ?? "")) {
        updates.endpoints = { [providerId]: form.endpoint };
      }

      if (!updates.api_keys && !updates.endpoints) {
        updateForm(providerId, { saving: false });
        return;
      }

      const data = await api.updateSettings(updates);
      setProviders(data.providers);
      updateForm(providerId, {
        apiKey: "",
        saving: false,
        feedback: { type: "success", message: "Saved" },
      });
      // Clear cached models so they reload with new key
      setModelsMap((prev) => {
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
      setTimeout(() => updateForm(providerId, { feedback: null }), 3000);
    } catch (e) {
      updateForm(providerId, {
        saving: false,
        feedback: { type: "error", message: String(e) },
      });
    }
  }

  async function clearKey(providerId: string) {
    updateForm(providerId, { saving: true, feedback: null });
    try {
      const data = await api.updateSettings({
        api_keys: { [providerId]: "" },
      });
      setProviders(data.providers);
      setModelsMap((prev) => {
        const next = { ...prev };
        delete next[providerId];
        return next;
      });
      updateForm(providerId, {
        apiKey: "",
        saving: false,
        feedback: { type: "success", message: "Key cleared" },
      });
      setTimeout(() => updateForm(providerId, { feedback: null }), 3000);
    } catch (e) {
      updateForm(providerId, {
        saving: false,
        feedback: { type: "error", message: String(e) },
      });
    }
  }

  async function loadModels(providerId: string) {
    setModelsMap((prev) => ({
      ...prev,
      [providerId]: { loading: true, models: [], error: null, loaded: false },
    }));

    try {
      const result = await api.fetchModels(providerId);
      setModelsMap((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          models: result.models,
          error: result.error,
          loaded: true,
        },
      }));
    } catch (e) {
      setModelsMap((prev) => ({
        ...prev,
        [providerId]: {
          loading: false,
          models: [],
          error: String(e),
          loaded: true,
        },
      }));
    }
  }

  if (loading) {
    return <p className="text-gray-500">Loading settings...</p>;
  }

  if (error) {
    return (
      <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded">
        {error}
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-2">LLM Settings</h2>
      <p className="text-gray-500 text-sm mb-6">
        Configure API keys for each LLM provider. Keys are stored in your
        workspace and used when agents run.
      </p>

      <div className="space-y-4">
        {providers.map((provider) => {
          const form = forms[provider.id];
          if (!form) return null;
          const isOllama = provider.id === "ollama";
          const ms = modelsMap[provider.id];

          return (
            <div
              key={provider.id}
              className="bg-white rounded-lg shadow p-5 border border-gray-100"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-base font-semibold text-gray-900">
                  {provider.name}
                </h3>
                <span
                  className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${
                    provider.has_key
                      ? "bg-green-100 text-green-800"
                      : "bg-gray-100 text-gray-500"
                  }`}
                >
                  {provider.has_key ? "Configured" : "Not set"}
                </span>
              </div>

              {!isOllama && (
                <div className="space-y-3">
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-1">
                      API Key
                    </label>
                    <div className="flex gap-2">
                      <div className="relative flex-1">
                        <input
                          type={form.showKey ? "text" : "password"}
                          value={form.apiKey}
                          onChange={(e) =>
                            updateForm(provider.id, { apiKey: e.target.value })
                          }
                          placeholder={
                            provider.has_key
                              ? "********** (key set)"
                              : "Enter API key..."
                          }
                          className="w-full border border-gray-300 rounded-md px-3 py-2 pr-16 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
                        />
                        <button
                          type="button"
                          onClick={() =>
                            updateForm(provider.id, { showKey: !form.showKey })
                          }
                          className="absolute right-2 top-1/2 -translate-y-1/2 text-xs text-gray-400 hover:text-gray-600"
                        >
                          {form.showKey ? "Hide" : "Show"}
                        </button>
                      </div>
                      <button
                        onClick={() => void saveKey(provider.id)}
                        disabled={form.saving || !form.apiKey}
                        className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50 whitespace-nowrap"
                      >
                        {form.saving ? "Saving..." : "Save"}
                      </button>
                      {provider.has_key && (
                        <button
                          onClick={() => void clearKey(provider.id)}
                          disabled={form.saving}
                          className="px-3 py-2 text-sm text-red-600 border border-red-200 rounded-md hover:bg-red-50 disabled:opacity-50"
                        >
                          Clear
                        </button>
                      )}
                    </div>
                  </div>

                  {form.feedback && (
                    <p
                      className={`text-sm ${
                        form.feedback.type === "success"
                          ? "text-green-600"
                          : "text-red-600"
                      }`}
                    >
                      {form.feedback.message}
                    </p>
                  )}
                </div>
              )}

              {isOllama && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">
                    Endpoint
                  </label>
                  <div className="flex gap-2">
                    <input
                      type="text"
                      value={form.endpoint}
                      onChange={(e) =>
                        updateForm(provider.id, { endpoint: e.target.value })
                      }
                      placeholder="http://localhost:11434"
                      className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm font-mono focus:ring-indigo-500 focus:border-indigo-500"
                    />
                    <button
                      onClick={() => void saveKey(provider.id)}
                      disabled={form.saving}
                      className="px-4 py-2 bg-indigo-600 text-white text-sm rounded-md hover:bg-indigo-700 disabled:opacity-50"
                    >
                      {form.saving ? "Saving..." : "Save"}
                    </button>
                  </div>
                  {form.feedback && (
                    <p
                      className={`text-sm mt-2 ${
                        form.feedback.type === "success"
                          ? "text-green-600"
                          : "text-red-600"
                      }`}
                    >
                      {form.feedback.message}
                    </p>
                  )}
                </div>
              )}

              {/* Models section — fetch on demand */}
              <div className="mt-3 pt-3 border-t border-gray-100">
                {!ms || !ms.loaded ? (
                  <button
                    onClick={() => void loadModels(provider.id)}
                    disabled={ms?.loading || (!provider.has_key && !isOllama)}
                    className="text-sm text-indigo-600 hover:text-indigo-800 disabled:text-gray-400 disabled:cursor-not-allowed"
                  >
                    {ms?.loading
                      ? "Loading models..."
                      : !provider.has_key && !isOllama
                        ? "Set API key to view models"
                        : "Fetch available models"}
                  </button>
                ) : (
                  <div>
                    <div className="flex items-center justify-between mb-1.5">
                      <p className="text-xs font-medium text-gray-500">
                        Available Models ({ms.models.length})
                      </p>
                      <button
                        onClick={() => void loadModels(provider.id)}
                        className="text-xs text-indigo-500 hover:text-indigo-700"
                      >
                        Refresh
                      </button>
                    </div>
                    {ms.error && (
                      <p className="text-xs text-red-500 mb-1.5">{ms.error}</p>
                    )}
                    {ms.models.length > 0 ? (
                      <div className="flex flex-wrap gap-1.5 max-h-32 overflow-y-auto">
                        {ms.models.map((m) => (
                          <span
                            key={m.id}
                            className="inline-block bg-gray-100 text-gray-700 text-xs px-2 py-0.5 rounded font-mono"
                            title={m.name !== m.id ? m.name : undefined}
                          >
                            {m.id}
                          </span>
                        ))}
                      </div>
                    ) : (
                      !ms.error && (
                        <p className="text-xs text-gray-400">No models found</p>
                      )
                    )}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
