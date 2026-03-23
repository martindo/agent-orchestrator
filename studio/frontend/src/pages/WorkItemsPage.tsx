import { useState } from "react";
import { useTeamStore } from "../store/teamStore";
import { Modal } from "../components/common/Modal";
import type {
  WorkItemTypeSpec,
  WorkItemFieldSpec,
  ArtifactTypeSpec,
} from "../types";

const FIELD_TYPES = [
  "text",
  "string",
  "integer",
  "float",
  "enum",
  "boolean",
] as const;

type FieldType = (typeof FIELD_TYPES)[number];

function emptyWorkItemType(): WorkItemTypeSpec {
  return {
    id: "",
    name: "",
    description: "",
    custom_fields: [],
    artifact_types: [],
  };
}

interface FieldFormState {
  name: string;
  type: FieldType;
  required: boolean;
  values: string;
}

function emptyFieldForm(): FieldFormState {
  return { name: "", type: "string", required: false, values: "" };
}

interface ArtifactFormState {
  id: string;
  name: string;
  extensions: string;
}

function emptyArtifactForm(): ArtifactFormState {
  return { id: "", name: "", extensions: "" };
}

export function WorkItemsPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const addWorkItemType = useTeamStore((s) => s.addWorkItemType);
  const updateWorkItemType = useTeamStore((s) => s.updateWorkItemType);
  const removeWorkItemType = useTeamStore((s) => s.removeWorkItemType);

  const [modalOpen, setModalOpen] = useState(false);
  const [editIdx, setEditIdx] = useState<number | null>(null);
  const [form, setForm] = useState<WorkItemTypeSpec>(emptyWorkItemType());
  const [fieldForm, setFieldForm] = useState<FieldFormState>(emptyFieldForm());
  const [artifactForm, setArtifactForm] = useState<ArtifactFormState>(
    emptyArtifactForm(),
  );
  const [deleteConfirm, setDeleteConfirm] = useState<number | null>(null);

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  const wits = team.work_item_types;

  function openAdd() {
    setForm(emptyWorkItemType());
    setFieldForm(emptyFieldForm());
    setArtifactForm(emptyArtifactForm());
    setEditIdx(null);
    setModalOpen(true);
  }

  function openEdit(index: number) {
    const wit = wits[index];
    if (!wit) return;
    setForm(wit);
    setFieldForm(emptyFieldForm());
    setArtifactForm(emptyArtifactForm());
    setEditIdx(index);
    setModalOpen(true);
  }

  function handleSave() {
    if (editIdx !== null) {
      void updateWorkItemType(editIdx, form);
    } else {
      void addWorkItemType(form);
    }
    setModalOpen(false);
  }

  function addField() {
    if (!fieldForm.name.trim()) return;
    const field: WorkItemFieldSpec = {
      name: fieldForm.name.trim(),
      type: fieldForm.type,
      required: fieldForm.required,
      default: null,
      values:
        fieldForm.type === "enum" && fieldForm.values.trim()
          ? fieldForm.values
              .split(",")
              .map((v) => v.trim())
              .filter(Boolean)
          : null,
    };
    setForm({ ...form, custom_fields: [...form.custom_fields, field] });
    setFieldForm(emptyFieldForm());
  }

  function removeField(idx: number) {
    setForm({
      ...form,
      custom_fields: form.custom_fields.filter((_, i) => i !== idx),
    });
  }

  function addArtifact() {
    if (!artifactForm.id.trim() || !artifactForm.name.trim()) return;
    const artifact: ArtifactTypeSpec = {
      id: artifactForm.id.trim(),
      name: artifactForm.name.trim(),
      description: "",
      file_extensions: artifactForm.extensions
        .split(",")
        .map((e) => e.trim())
        .filter(Boolean),
    };
    setForm({
      ...form,
      artifact_types: [...form.artifact_types, artifact],
    });
    setArtifactForm(emptyArtifactForm());
  }

  function removeArtifact(idx: number) {
    setForm({
      ...form,
      artifact_types: form.artifact_types.filter((_, i) => i !== idx),
    });
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h2 className="text-2xl font-bold">Work Item Types</h2>
        <button
          onClick={openAdd}
          className="bg-indigo-600 text-white px-4 py-2 rounded-md hover:bg-indigo-700 text-sm font-medium"
        >
          + Add Type
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {wits.length === 0 ? (
        <div className="bg-white rounded-lg shadow p-8 text-center text-gray-500">
          No work item types defined yet.
        </div>
      ) : (
        <div className="space-y-3">
          {wits.map((wit, i) => (
            <div
              key={wit.id}
              className="bg-white rounded-lg shadow p-4 flex items-start justify-between"
            >
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <h3 className="font-semibold text-sm">{wit.name}</h3>
                  <span className="text-xs text-gray-400 font-mono">
                    {wit.id}
                  </span>
                </div>
                <p className="text-sm text-gray-600 mt-1">
                  {wit.description || "No description"}
                </p>
                <div className="text-xs text-gray-400 mt-1">
                  {wit.custom_fields.length} field
                  {wit.custom_fields.length !== 1 ? "s" : ""},{" "}
                  {wit.artifact_types.length} artifact type
                  {wit.artifact_types.length !== 1 ? "s" : ""}
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
                      onClick={() => {
                        void removeWorkItemType(i);
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

      {/* Modal */}
      <Modal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        title={editIdx !== null ? "Edit Work Item Type" : "Add Work Item Type"}
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
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
                disabled={editIdx !== null}
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
              />
            </div>
          </div>

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

          {/* Custom Fields */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Custom Fields
            </legend>
            {form.custom_fields.length > 0 && (
              <div className="space-y-2 mb-3">
                {form.custom_fields.map((field, fi) => (
                  <div
                    key={fi}
                    className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{field.name}</span>
                      <span className="text-xs bg-blue-100 text-blue-700 px-2 py-0.5 rounded">
                        {field.type}
                      </span>
                      {field.required && (
                        <span className="text-xs bg-red-100 text-red-600 px-2 py-0.5 rounded">
                          required
                        </span>
                      )}
                      {field.values && field.values.length > 0 && (
                        <span className="text-xs text-gray-400">
                          [{field.values.join(", ")}]
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => removeField(fi)}
                      className="text-red-500 hover:text-red-700 text-xs"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-3">
                <label className="block text-xs text-gray-600 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={fieldForm.name}
                  onChange={(e) =>
                    setFieldForm({ ...fieldForm, name: e.target.value })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                />
              </div>
              <div className="col-span-2">
                <label className="block text-xs text-gray-600 mb-1">
                  Type
                </label>
                <select
                  value={fieldForm.type}
                  onChange={(e) =>
                    setFieldForm({
                      ...fieldForm,
                      type: e.target.value as FieldType,
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                >
                  {FIELD_TYPES.map((t) => (
                    <option key={t} value={t}>
                      {t}
                    </option>
                  ))}
                </select>
              </div>
              <div className="col-span-1 flex items-center justify-center pt-4">
                <label className="flex items-center gap-1 text-xs">
                  <input
                    type="checkbox"
                    checked={fieldForm.required}
                    onChange={(e) =>
                      setFieldForm({ ...fieldForm, required: e.target.checked })
                    }
                    className="rounded"
                  />
                  Req
                </label>
              </div>
              <div className="col-span-4">
                <label className="block text-xs text-gray-600 mb-1">
                  Values (enum, comma-sep)
                </label>
                <input
                  type="text"
                  value={fieldForm.values}
                  onChange={(e) =>
                    setFieldForm({ ...fieldForm, values: e.target.value })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                  disabled={fieldForm.type !== "enum"}
                  placeholder={
                    fieldForm.type === "enum" ? "val1, val2, val3" : ""
                  }
                />
              </div>
              <div className="col-span-2">
                <button
                  type="button"
                  onClick={addField}
                  className="w-full px-2 py-1.5 bg-gray-200 text-gray-700 rounded-md text-sm hover:bg-gray-300"
                >
                  Add
                </button>
              </div>
            </div>
          </fieldset>

          {/* Artifact Types */}
          <fieldset className="border border-gray-200 rounded-md p-4">
            <legend className="text-sm font-medium text-gray-700 px-1">
              Artifact Types
            </legend>
            {form.artifact_types.length > 0 && (
              <div className="space-y-2 mb-3">
                {form.artifact_types.map((art, ai) => (
                  <div
                    key={ai}
                    className="flex items-center justify-between bg-gray-50 rounded px-3 py-2 text-sm"
                  >
                    <div className="flex items-center gap-2">
                      <span className="font-medium">{art.name}</span>
                      <span className="text-xs text-gray-400 font-mono">
                        {art.id}
                      </span>
                      {art.file_extensions.length > 0 && (
                        <span className="text-xs text-gray-400">
                          {art.file_extensions.join(", ")}
                        </span>
                      )}
                    </div>
                    <button
                      onClick={() => removeArtifact(ai)}
                      className="text-red-500 hover:text-red-700 text-xs"
                    >
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            )}
            <div className="grid grid-cols-12 gap-2 items-end">
              <div className="col-span-3">
                <label className="block text-xs text-gray-600 mb-1">ID</label>
                <input
                  type="text"
                  value={artifactForm.id}
                  onChange={(e) =>
                    setArtifactForm({ ...artifactForm, id: e.target.value })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                />
              </div>
              <div className="col-span-3">
                <label className="block text-xs text-gray-600 mb-1">
                  Name
                </label>
                <input
                  type="text"
                  value={artifactForm.name}
                  onChange={(e) =>
                    setArtifactForm({ ...artifactForm, name: e.target.value })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                />
              </div>
              <div className="col-span-4">
                <label className="block text-xs text-gray-600 mb-1">
                  Extensions (comma-sep)
                </label>
                <input
                  type="text"
                  value={artifactForm.extensions}
                  onChange={(e) =>
                    setArtifactForm({
                      ...artifactForm,
                      extensions: e.target.value,
                    })
                  }
                  className="w-full border border-gray-300 rounded-md px-2 py-1.5 text-sm"
                  placeholder=".md, .txt, .json"
                />
              </div>
              <div className="col-span-2">
                <button
                  type="button"
                  onClick={addArtifact}
                  className="w-full px-2 py-1.5 bg-gray-200 text-gray-700 rounded-md text-sm hover:bg-gray-300"
                >
                  Add
                </button>
              </div>
            </div>
          </fieldset>

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
              {loading ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
