import { useState, useEffect } from "react";
import { useTeamStore } from "../store/teamStore";
import * as api from "../api/client";
import type { TemplateInfo } from "../types";

export function OverviewPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const createTeam = useTeamStore((s) => s.createTeam);
  const importTemplate = useTeamStore((s) => s.importTemplate);
  const loadTeam = useTeamStore((s) => s.loadTeam);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [templates, setTemplates] = useState<readonly TemplateInfo[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState("");
  const [templateError, setTemplateError] = useState<string | null>(null);

  useEffect(() => {
    api.listTemplates().then(
      (res) => setTemplates(res.templates),
      () => setTemplateError("Failed to load templates"),
    );
  }, []);

  useEffect(() => {
    if (!team) {
      loadTeam().catch(() => {
        /* team may not exist yet */
      });
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    void createTeam(name.trim(), description.trim());
  }

  function handleImport() {
    if (!selectedTemplate) return;
    void importTemplate(selectedTemplate);
  }

  if (team) {
    const agentCount = team.agents.length;
    const phaseCount = team.workflow.phases.length;
    const statusCount = team.workflow.statuses.length;
    const policyCount = team.governance.policies.length;
    const witCount = team.work_item_types.length;

    return (
      <div>
        <h2 className="text-2xl font-bold mb-6">Team Overview</h2>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
            {error}
          </div>
        )}

        <div className="bg-white rounded-lg shadow p-6 mb-6">
          <h3 className="text-xl font-semibold mb-2">{team.name}</h3>
          <p className="text-gray-600 mb-4">
            {team.description || "No description"}
          </p>
        </div>

        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <StatCard label="Agents" value={agentCount} />
          <StatCard label="Phases" value={phaseCount} />
          <StatCard label="Statuses" value={statusCount} />
          <StatCard label="Policies" value={policyCount} />
          <StatCard label="Work Item Types" value={witCount} />
        </div>
      </div>
    );
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Create or Import a Team</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* Create new team */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">Create New Team</h3>
          <form onSubmit={handleCreate} className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Team Name
              </label>
              <input
                type="text"
                value={name}
                onChange={(e) => setName(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="my-agent-team"
                required
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">
                Description
              </label>
              <input
                type="text"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                placeholder="Optional description"
              />
            </div>
            <button
              type="submit"
              disabled={loading || !name.trim()}
              className="w-full bg-indigo-600 text-white py-2 px-4 rounded-md hover:bg-indigo-700 disabled:opacity-50 text-sm font-medium"
            >
              {loading ? "Creating..." : "Create Team"}
            </button>
          </form>
        </div>

        {/* Import from template */}
        <div className="bg-white rounded-lg shadow p-6">
          <h3 className="text-lg font-semibold mb-4">Import Template</h3>
          {templateError && (
            <p className="text-sm text-red-600 mb-2">{templateError}</p>
          )}
          {templates.length === 0 && !templateError ? (
            <p className="text-sm text-gray-500">No templates available.</p>
          ) : (
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">
                  Select Template
                </label>
                <select
                  value={selectedTemplate}
                  onChange={(e) => setSelectedTemplate(e.target.value)}
                  className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm focus:ring-indigo-500 focus:border-indigo-500"
                >
                  <option value="">-- Choose a template --</option>
                  {templates.map((t) => (
                    <option key={t.name} value={t.name}>
                      {t.name}
                    </option>
                  ))}
                </select>
              </div>
              <button
                onClick={handleImport}
                disabled={loading || !selectedTemplate}
                className="w-full bg-green-600 text-white py-2 px-4 rounded-md hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
              >
                {loading ? "Importing..." : "Import Template"}
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function StatCard({
  label,
  value,
}: {
  readonly label: string;
  readonly value: number;
}) {
  return (
    <div className="bg-white rounded-lg shadow p-4 text-center">
      <p className="text-3xl font-bold text-indigo-600">{value}</p>
      <p className="text-sm text-gray-500 mt-1">{label}</p>
    </div>
  );
}
