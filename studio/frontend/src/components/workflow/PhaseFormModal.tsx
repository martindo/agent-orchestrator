import { useState } from "react";
import { Modal } from "../common/Modal";
import type { PhaseSpec, AgentSpec, QualityGateSpec } from "../../types";

/** Convert a display name to a kebab-case ID slug */
function slugify(name: string): string {
  return name
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

interface PhaseFormModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
  readonly phase: PhaseSpec;
  readonly onChange: (phase: PhaseSpec) => void;
  readonly onSave: () => void;
  readonly isEdit: boolean;
  readonly loading: boolean;
  readonly agents: readonly AgentSpec[];
  readonly phases: readonly PhaseSpec[];
}

export function PhaseFormModal({
  open,
  onClose,
  phase,
  onChange,
  onSave,
  isEdit,
  loading,
  agents,
  phases,
}: PhaseFormModalProps) {
  const [newGateName, setNewGateName] = useState("");
  const [manualId, setManualId] = useState(false);

  const existingIds = phases.map((p) => p.id);

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
    if (manualId || isEdit) {
      onChange({ ...phase, name });
    } else {
      onChange({ ...phase, name, id: generateId(name) });
    }
  }

  function toggleAgent(agentId: string) {
    const current = [...phase.agents];
    const idx = current.indexOf(agentId);
    if (idx >= 0) current.splice(idx, 1);
    else current.push(agentId);
    onChange({ ...phase, agents: current });
  }

  function addQualityGate() {
    if (!newGateName.trim()) return;
    const gate: QualityGateSpec = {
      name: newGateName.trim(),
      description: "",
      conditions: [],
      on_failure: "block",
    };
    onChange({
      ...phase,
      quality_gates: [...phase.quality_gates, gate],
    });
    setNewGateName("");
  }

  function removeQualityGate(idx: number) {
    onChange({
      ...phase,
      quality_gates: phase.quality_gates.filter((_, i) => i !== idx),
    });
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={isEdit ? "Edit Phase" : "Add Phase"}
      wide
    >
      <div className="space-y-4">
        <div className="grid grid-cols-3 gap-4">
          <div className="col-span-2">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Name
            </label>
            <input
              type="text"
              value={phase.name}
              onChange={(e) => handleNameChange(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="e.g. Research & Analysis"
              autoFocus={!isEdit}
            />
            {phase.id && (
              <p className="text-xs text-gray-400 mt-1">
                ID: <span className="font-mono">{phase.id}</span>
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
                value={phase.id}
                onChange={(e) => onChange({ ...phase, id: e.target.value })}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm mt-1"
                placeholder="custom-phase-id"
              />
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Order
            </label>
            <input
              type="number"
              value={phase.order}
              onChange={(e) =>
                onChange({
                  ...phase,
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
            value={phase.description}
            onChange={(e) =>
              onChange({ ...phase, description: e.target.value })
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
                const selected = phase.agents.includes(a.id);
                return (
                  <button
                    key={a.id}
                    type="button"
                    onClick={() => toggleAgent(a.id)}
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
          {phase.required_capabilities.length > 0 && (
            <div className="flex flex-wrap gap-2 mb-3">
              {phase.required_capabilities.map((cap, ci) => (
                <span
                  key={ci}
                  className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-full bg-blue-100 border border-blue-300 text-blue-700"
                >
                  {cap}
                  <button
                    type="button"
                    onClick={() => {
                      onChange({
                        ...phase,
                        required_capabilities:
                          phase.required_capabilities.filter(
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
              placeholder="Add capability (press Enter)"
              className="flex-1 border border-gray-300 rounded-md px-3 py-2 text-sm"
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  const input = e.currentTarget;
                  const val = input.value.trim();
                  if (val && !phase.required_capabilities.includes(val)) {
                    onChange({
                      ...phase,
                      required_capabilities: [
                        ...phase.required_capabilities,
                        val,
                      ],
                    });
                    input.value = "";
                  }
                }
              }}
            />
          </div>
          {(() => {
            const allSkills = new Set(agents.flatMap((a) => [...a.skills]));
            const unused = [...allSkills].filter(
              (s) => !phase.required_capabilities.includes(s)
            );
            if (unused.length === 0) return null;
            return (
              <div className="mt-2">
                <span className="text-xs text-gray-400">
                  Available skills:{" "}
                </span>
                <div className="flex flex-wrap gap-1 mt-1">
                  {unused.map((skill) => (
                    <button
                      key={skill}
                      type="button"
                      onClick={() => {
                        onChange({
                          ...phase,
                          required_capabilities: [
                            ...phase.required_capabilities,
                            skill,
                          ],
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
              value={phase.on_success}
              onChange={(e) =>
                onChange({ ...phase, on_success: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              <option value="">-- None --</option>
              {phases
                .filter((p) => p.id !== phase.id)
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
              value={phase.on_failure}
              onChange={(e) =>
                onChange({ ...phase, on_failure: e.target.value })
              }
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            >
              <option value="">-- None --</option>
              {phases
                .filter((p) => p.id !== phase.id)
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
          {phase.quality_gates.length > 0 && (
            <div className="space-y-2 mb-3">
              {phase.quality_gates.map((gate, gi) => (
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
              checked={phase.is_terminal}
              onChange={(e) =>
                onChange({ ...phase, is_terminal: e.target.checked })
              }
              className="rounded"
            />
            Terminal
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={phase.requires_human}
              onChange={(e) =>
                onChange({ ...phase, requires_human: e.target.checked })
              }
              className="rounded"
            />
            Requires Human
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={phase.parallel}
              onChange={(e) =>
                onChange({ ...phase, parallel: e.target.checked })
              }
              className="rounded"
            />
            Parallel
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={phase.skippable}
              onChange={(e) =>
                onChange({ ...phase, skippable: e.target.checked })
              }
              className="rounded"
            />
            Skippable
          </label>
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 pt-2">
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            onClick={onSave}
            disabled={loading || !phase.id.trim() || !phase.name.trim()}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            {loading ? "Saving..." : "Save Phase"}
          </button>
        </div>
      </div>
    </Modal>
  );
}
