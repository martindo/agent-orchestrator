import { useEffect, useState } from "react";
import { useTeamStore } from "../store/teamStore";

const TABS = [
  { key: "agents.yaml", label: "Agents" },
  { key: "workflow.yaml", label: "Workflow" },
  { key: "governance.yaml", label: "Governance" },
  { key: "workitems.yaml", label: "Work Items" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function PreviewPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);
  const yamlPreview = useTeamStore((s) => s.yamlPreview);
  const validation = useTeamStore((s) => s.validation);
  const loadPreview = useTeamStore((s) => s.loadPreview);
  const validate = useTeamStore((s) => s.validate);

  const [activeTab, setActiveTab] = useState<TabKey>("agents.yaml");

  useEffect(() => {
    if (team && !yamlPreview) {
      void loadPreview();
    }
  }, [team]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  const currentYaml = yamlPreview?.[activeTab] ?? "";

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-2xl font-bold">YAML Preview</h2>
        <div className="flex gap-2">
          <button
            onClick={() => void loadPreview()}
            disabled={loading}
            className="px-4 py-2 text-sm bg-gray-200 text-gray-700 rounded-md hover:bg-gray-300 disabled:opacity-50"
          >
            {loading ? "Loading..." : "Refresh"}
          </button>
          <button
            onClick={() => void validate()}
            disabled={loading}
            className="px-4 py-2 text-sm bg-indigo-600 text-white rounded-md hover:bg-indigo-700 disabled:opacity-50"
          >
            Validate
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      {/* Validation Results */}
      {validation && (
        <div
          className={`border rounded-md px-4 py-3 mb-4 ${
            validation.is_valid
              ? "bg-green-50 border-green-200"
              : "bg-red-50 border-red-200"
          }`}
        >
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`font-semibold text-sm ${
                validation.is_valid ? "text-green-700" : "text-red-700"
              }`}
            >
              {validation.is_valid ? "Valid" : "Invalid"}
            </span>
            <span className="text-xs text-gray-500">
              {validation.error_count} error
              {validation.error_count !== 1 ? "s" : ""},{" "}
              {validation.warning_count} warning
              {validation.warning_count !== 1 ? "s" : ""}
            </span>
          </div>
          {validation.errors.length > 0 && (
            <div className="space-y-1 mb-2">
              {validation.errors.map((err, i) => (
                <div key={i} className="text-sm text-red-700">
                  <span className="font-mono text-xs text-red-500">
                    {err.path}
                  </span>{" "}
                  {err.message}
                </div>
              ))}
            </div>
          )}
          {validation.warnings.length > 0 && (
            <div className="space-y-1">
              {validation.warnings.map((warn, i) => (
                <div key={i} className="text-sm text-yellow-700">
                  <span className="font-mono text-xs text-yellow-600">
                    {warn.path}
                  </span>{" "}
                  {warn.message}
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Tabs */}
      <div className="flex gap-1 border-b mb-0">
        {TABS.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setActiveTab(tab.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              activeTab === tab.key
                ? "border-indigo-600 text-indigo-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {/* YAML Content */}
      <div className="bg-gray-900 rounded-b-lg overflow-auto">
        {loading && !yamlPreview ? (
          <div className="p-6 text-gray-400 text-sm">Loading preview...</div>
        ) : currentYaml ? (
          <pre className="p-4 text-sm text-green-300 font-mono whitespace-pre overflow-x-auto leading-relaxed">
            {currentYaml}
          </pre>
        ) : (
          <div className="p-6 text-gray-500 text-sm">
            No content for this file. Make sure you have relevant data defined.
          </div>
        )}
      </div>
    </div>
  );
}
