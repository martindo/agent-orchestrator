import { useState } from "react";
import { useTeamStore } from "../store/teamStore";
import { Modal } from "../components/common/Modal";
import type { PolicySpec, DelegatedAuthoritySpec } from "../types";

const POLICY_ACTIONS = [
  "approve",
  "reject",
  "review",
  "escalate",
  "warn",
  "block",
] as const;

function emptyPolicy(): PolicySpec {
  return {
    id: "",
    name: "",
    description: "",
    scope: "global",
    action: "review",
    conditions: [],
    priority: 0,
    enabled: true,
    tags: [],
  };
}

export function GovernancePage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const updateTeam = useTeamStore((s) => s.updateTeam);
  const addPolicy = useTeamStore((s) => s.addPolicy);
  const updatePolicy = useTeamStore((s) => s.updatePolicy);
  const removePolicy = useTeamStore((s) => s.removePolicy);

  const [policyModalOpen, setPolicyModalOpen] = useState(false);
  const [policyEditIdx, setPolicyEditIdx] = useState<number | null>(null);
  const [policyForm, setPolicyForm] = useState<PolicySpec>(emptyPolicy());
  const [newCondition, setNewCondition] = useState("");
  const [newTag, setNewTag] = useState("");
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  const { delegated_authority, policies } = team.governance;

  function handleThresholdChange(
    field: "auto_approve_threshold" | "review_threshold" | "abort_threshold",
    value: number,
  ) {
    const current = useTeamStore.getState().team;
    if (!current) return;
    void updateTeam({
      ...current,
      governance: {
        ...current.governance,
        delegated_authority: {
          ...current.governance.delegated_authority,
          [field]: value,
        },
      },
    });
  }

  function openAddPolicy() {
    setPolicyForm(emptyPolicy());
    setPolicyEditIdx(null);
    setPolicyModalOpen(true);
  }

  function openEditPolicy(index: number) {
    const p = policies[index];
    if (!p) return;
    setPolicyForm(p);
    setPolicyEditIdx(index);
    setPolicyModalOpen(true);
  }

  function handleSavePolicy() {
    if (policyEditIdx !== null) {
      void updatePolicy(policyEditIdx, policyForm);
    } else {
      void addPolicy(policyForm);
    }
    setPolicyModalOpen(false);
  }

  function addConditionToForm() {
    if (!newCondition.trim()) return;
    setPolicyForm({
      ...policyForm,
      conditions: [...policyForm.conditions, newCondition.trim()],
    });
    setNewCondition("");
  }

  function removeConditionFromForm(idx: number) {
    setPolicyForm({
      ...policyForm,
      conditions: policyForm.conditions.filter((_, i) => i !== idx),
    });
  }

  function addTagToForm() {
    if (!newTag.trim()) return;
    setPolicyForm({
      ...policyForm,
      tags: [...policyForm.tags, newTag.trim()],
    });
    setNewTag("");
  }

  function removeTagFromForm(idx: number) {
    setPolicyForm({
      ...policyForm,
      tags: policyForm.tags.filter((_, i) => i !== idx),
    });
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Governance</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Delegated Authority */}
      <div className="bg-white rounded-lg shadow p-6 mb-6">
        <h3 className="text-lg font-semibold mb-4">Delegated Authority</h3>
        <div className="space-y-5">
          <ThresholdSlider
            label="Auto-Approve Threshold"
            value={delegated_authority.auto_approve_threshold}
            onChange={(v) => handleThresholdChange("auto_approve_threshold", v)}
          />
          <ThresholdSlider
            label="Review Threshold"
            value={delegated_authority.review_threshold}
            onChange={(v) => handleThresholdChange("review_threshold", v)}
          />
          <ThresholdSlider
            label="Abort Threshold"
            value={delegated_authority.abort_threshold}
            onChange={(v) => handleThresholdChange("abort_threshold", v)}
          />
        </div>
      </div>

      {/* Policies */}
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold">Policies</h3>
        <button
          onClick={openAddPolicy}
          className="bg-indigo-600 text-white px-4 py-2 rounded-md hover:bg-indigo-700 text-sm font-medium"
        >
          + Add Policy
        </button>
      </div>

      {policies.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No policies defined yet.
        </div>
      ) : (
        <div className="space-y-2">
          {policies.map((policy, i) => (
            <div
              key={policy.id}
              className="bg-white rounded-lg shadow p-4 flex items-start justify-between"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h4 className="font-semibold text-sm">{policy.name}</h4>
                  <span className="text-xs text-gray-400 font-mono">
                    {policy.id}
                  </span>
                  <span
                    className={`text-xs px-2 py-0.5 rounded ${
                      policy.enabled
                        ? "bg-green-100 text-green-700"
                        : "bg-gray-200 text-gray-500"
                    }`}
                  >
                    {policy.enabled ? "enabled" : "disabled"}
                  </span>
                  <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                    {policy.action}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mt-1">
                  {policy.description || "No description"}
                </p>
                <div className="flex flex-wrap gap-1 mt-1">
                  {policy.tags.map((tag) => (
                    <span
                      key={tag}
                      className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded"
                    >
                      {tag}
                    </span>
                  ))}
                </div>
              </div>
              <div className="flex gap-2 ml-4 shrink-0">
                <button
                  onClick={() => openEditPolicy(i)}
                  className="text-sm text-indigo-600 hover:text-indigo-800"
                >
                  Edit
                </button>
                {deleteConfirm === i ? (
                  <div className="flex gap-1">
                    <button
                      onClick={() => {
                        void removePolicy(i);
                        setDeleteConfirm(null);
                      }}
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

      {/* Policy Modal */}
      <Modal
        open={policyModalOpen}
        onClose={() => setPolicyModalOpen(false)}
        title={policyEditIdx !== null ? "Edit Policy" : "Add Policy"}
        wide
      >
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                ID
              </label>
              <input
                type="text"
                value={policyForm.id}
                onChange={(e) =>
                  setPolicyForm({ ...policyForm, id: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                disabled={policyEditIdx !== null}
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Name
              </label>
              <input
                type="text"
                value={policyForm.name}
                onChange={(e) =>
                  setPolicyForm({ ...policyForm, name: e.target.value })
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
              value={policyForm.description}
              onChange={(e) =>
                setPolicyForm({ ...policyForm, description: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Scope
              </label>
              <input
                type="text"
                value={policyForm.scope}
                onChange={(e) =>
                  setPolicyForm({ ...policyForm, scope: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                placeholder="global"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Action
              </label>
              <select
                value={policyForm.action}
                onChange={(e) =>
                  setPolicyForm({ ...policyForm, action: e.target.value })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              >
                {POLICY_ACTIONS.map((a) => (
                  <option key={a} value={a}>
                    {a}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Priority
              </label>
              <input
                type="number"
                value={policyForm.priority}
                onChange={(e) =>
                  setPolicyForm({
                    ...policyForm,
                    priority: parseInt(e.target.value, 10) || 0,
                  })
                }
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                min={0}
              />
            </div>
          </div>

          <label className="flex items-center gap-2 text-sm font-medium text-gray-700">
            <input
              type="checkbox"
              checked={policyForm.enabled}
              onChange={(e) =>
                setPolicyForm({ ...policyForm, enabled: e.target.checked })
              }
              className="rounded"
            />
            Enabled
          </label>

          {/* Conditions */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Conditions
            </legend>
            {policyForm.conditions.length > 0 && (
              <div className="space-y-1 mb-3">
                {policyForm.conditions.map((cond, ci) => (
                  <div
                    key={ci}
                    className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm font-mono"
                  >
                    <span className="truncate">{cond}</span>
                    <button
                      onClick={() => removeConditionFromForm(ci)}
                      className="text-red-500 hover:text-red-700 text-xs ml-2 shrink-0"
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
                value={newCondition}
                onChange={(e) => setNewCondition(e.target.value)}
                placeholder="e.g. risk_score > 0.7"
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addConditionToForm();
                  }
                }}
              />
              <button
                type="button"
                onClick={addConditionToForm}
                className="px-3 py-2 bg-gray-200 text-gray-700 rounded-md text-sm hover:bg-gray-300"
              >
                Add
              </button>
            </div>
          </fieldset>

          {/* Tags */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Tags
            </legend>
            {policyForm.tags.length > 0 && (
              <div className="flex flex-wrap gap-1 mb-3">
                {policyForm.tags.map((tag, ti) => (
                  <span
                    key={ti}
                    className="inline-flex items-center gap-1 text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded"
                  >
                    {tag}
                    <button
                      onClick={() => removeTagFromForm(ti)}
                      className="text-red-400 hover:text-red-600"
                    >
                      &times;
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <input
                type="text"
                value={newTag}
                onChange={(e) => setNewTag(e.target.value)}
                placeholder="tag name"
                className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    addTagToForm();
                  }
                }}
              />
              <button
                type="button"
                onClick={addTagToForm}
                className="px-3 py-2 bg-gray-200 text-gray-700 rounded-md text-sm hover:bg-gray-300"
              >
                Add
              </button>
            </div>
          </fieldset>

          <div className="flex justify-end gap-3 pt-2">
            <button
              onClick={() => setPolicyModalOpen(false)}
              className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={handleSavePolicy}
              disabled={
                loading || !policyForm.id.trim() || !policyForm.name.trim()
              }
              className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {loading ? "Saving..." : "Save Policy"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}

function ThresholdSlider({
  label,
  value,
  onChange,
}: {
  readonly label: string;
  readonly value: number;
  readonly onChange: (v: number) => void;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <label className="text-sm font-medium text-gray-700">{label}</label>
        <span className="text-sm font-mono text-gray-500">
          {value.toFixed(2)}
        </span>
      </div>
      <input
        type="range"
        min="0"
        max="1"
        step="0.01"
        value={value}
        onChange={(e) => onChange(parseFloat(e.target.value))}
        className="w-full"
      />
    </div>
  );
}
