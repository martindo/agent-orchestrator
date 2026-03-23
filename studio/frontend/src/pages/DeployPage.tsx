import { useState } from "react";
import { useTeamStore } from "../store/teamStore";

interface DeployResult {
  success: boolean;
  errors: readonly string[];
  warnings: readonly string[];
  filesWritten?: readonly string[];
  profileDir?: string;
  runtimeReloaded?: boolean;
}

export function DeployPage() {
  const team = useTeamStore((s) => s.team);
  const loading = useTeamStore((s) => s.loading);
  const error = useTeamStore((s) => s.error);

  const [profileName, setProfileName] = useState("");
  const [validateFirst, setValidateFirst] = useState(true);
  const [triggerReload, setTriggerReload] = useState(true);
  const [result, setResult] = useState<DeployResult | null>(null);
  const [deploying, setDeploying] = useState(false);

  if (!team) {
    return (
      <div className="text-gray-500">
        Load or create a team first from the Overview page.
      </div>
    );
  }

  async function handleDeploy() {
    setDeploying(true);
    setResult(null);
    try {
      const { deploy } = await import("../api/client");
      const res = await deploy({
        profile_name: profileName.trim() || undefined,
        validate_first: validateFirst,
        trigger_reload: triggerReload,
      });
      setResult({
        success: res.success,
        errors: res.errors,
        warnings: res.warnings,
        filesWritten: res.files_written,
        profileDir: res.profile_dir,
        runtimeReloaded: res.runtime_reloaded,
      });
    } catch (e: unknown) {
      const message = e instanceof Error ? e.message : String(e);
      setResult({
        success: false,
        errors: [message],
        warnings: [],
      });
    } finally {
      setDeploying(false);
    }
  }

  return (
    <div>
      <h2 className="text-2xl font-bold mb-6">Deploy</h2>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded mb-4">
          {error}
        </div>
      )}

      <div className="bg-white rounded-lg shadow p-6 max-w-xl">
        <h3 className="text-lg font-semibold mb-4">Deploy Configuration</h3>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Profile Name
            </label>
            <input
              type="text"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
              placeholder="default (leave blank for default)"
            />
          </div>

          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={validateFirst}
                onChange={(e) => setValidateFirst(e.target.checked)}
                className="rounded"
              />
              <span className="font-medium text-gray-700">
                Validate before deploying
              </span>
            </label>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={triggerReload}
                onChange={(e) => setTriggerReload(e.target.checked)}
                className="rounded"
              />
              <span className="font-medium text-gray-700">
                Trigger runtime reload after deploy
              </span>
            </label>
          </div>

          <button
            onClick={() => void handleDeploy()}
            disabled={deploying || loading}
            className="w-full bg-green-600 text-white py-2 px-4 rounded-md hover:bg-green-700 disabled:opacity-50 text-sm font-medium"
          >
            {deploying ? "Deploying..." : "Deploy Now"}
          </button>
        </div>
      </div>

      {/* Result */}
      {result && (
        <div
          className={`mt-6 border rounded-lg p-6 ${
            result.success
              ? "bg-green-50 border-green-200"
              : "bg-red-50 border-red-200"
          }`}
        >
          <h3
            className={`text-lg font-semibold mb-3 ${
              result.success ? "text-green-700" : "text-red-700"
            }`}
          >
            {result.success ? "Deployment Successful" : "Deployment Failed"}
          </h3>

          {result.profileDir && (
            <p className="text-sm text-gray-600 mb-2">
              Profile directory:{" "}
              <span className="font-mono">{result.profileDir}</span>
            </p>
          )}

          {result.runtimeReloaded !== undefined && (
            <p className="text-sm text-gray-600 mb-2">
              Runtime reloaded:{" "}
              <span className="font-medium">
                {result.runtimeReloaded ? "Yes" : "No"}
              </span>
            </p>
          )}

          {result.errors.length > 0 && (
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-red-700 mb-1">
                Errors
              </h4>
              <ul className="list-disc list-inside space-y-1">
                {result.errors.map((err, i) => (
                  <li key={i} className="text-sm text-red-600">
                    {err}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.warnings.length > 0 && (
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-yellow-700 mb-1">
                Warnings
              </h4>
              <ul className="list-disc list-inside space-y-1">
                {result.warnings.map((warn, i) => (
                  <li key={i} className="text-sm text-yellow-600">
                    {warn}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {result.filesWritten && result.filesWritten.length > 0 && (
            <div>
              <h4 className="text-sm font-semibold text-gray-700 mb-1">
                Files Written
              </h4>
              <ul className="space-y-1">
                {result.filesWritten.map((file, i) => (
                  <li
                    key={i}
                    className="text-sm font-mono text-gray-600 bg-white/60 rounded px-2 py-1"
                  >
                    {file}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
