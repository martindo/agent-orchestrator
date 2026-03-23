/**
 * AI Workflow Recommender page.
 *
 * Two tabs:
 * - Greenfield: type a project description, get agent/phase recommendations
 * - Existing Codebase: generate a prompt, paste analysis JSON, get recommendations
 */

import { useState } from "react";
import { useTeamStore } from "../store/teamStore";
import { RecommendReviewPanel } from "../components/recommend/RecommendReviewPanel";
import { Modal } from "../components/common/Modal";
import * as api from "../api/client";
import type { AgentSpec, PhaseSpec } from "../types";

type Tab = "greenfield" | "codebase";

interface RecommendedAgent {
  readonly agent: AgentSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface RecommendedPhase {
  readonly phase: PhaseSpec;
  readonly confidence: number;
  readonly reason: string;
}

interface RecommendationResult {
  readonly agents: readonly RecommendedAgent[];
  readonly phases: readonly RecommendedPhase[];
  readonly team_name_suggestion: string;
  readonly team_description_suggestion: string;
  readonly source: string;
}

export function RecommendPage() {
  const team = useTeamStore((s) => s.team);
  const bulkAddAgentsAndPhases = useTeamStore((s) => s.bulkAddAgentsAndPhases);

  const [tab, setTab] = useState<Tab>("greenfield");
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<RecommendationResult | null>(null);

  // Codebase tab state
  const [codebaseJson, setCodebaseJson] = useState("");
  const [generatedPrompt, setGeneratedPrompt] = useState<{ prompt: string; instructions: string } | null>(null);
  const [promptLoading, setPromptLoading] = useState(false);

  // Edit modal state
  const [editAgent, setEditAgent] = useState<AgentSpec | null>(null);
  const [editIndex, setEditIndex] = useState(-1);
  const [editForm, setEditForm] = useState({ name: "", description: "", system_prompt: "" });

  // ---- Greenfield ----
  async function handleGreenfield() {
    if (!description.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.recommendGreenfield(description);
      setResult(res as RecommendationResult);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  // ---- Codebase prompt ----
  async function handleGeneratePrompt() {
    setPromptLoading(true);
    setError(null);
    try {
      const res = await api.recommendCodebasePrompt(description || undefined);
      setGeneratedPrompt(res);
    } catch (e) {
      setError(String(e));
    } finally {
      setPromptLoading(false);
    }
  }

  // ---- Codebase analyze ----
  async function handleAnalyzeCodebase() {
    if (!codebaseJson.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const analysis = JSON.parse(codebaseJson);
      const res = await api.recommendFromCodebase(analysis);
      setResult(res as RecommendationResult);
    } catch (e) {
      if (e instanceof SyntaxError) {
        setError("Invalid JSON. Please paste the complete JSON output from your coding assistant.");
      } else {
        setError(String(e));
      }
    } finally {
      setLoading(false);
    }
  }

  // ---- Apply ----
  async function handleApply(agents: readonly AgentSpec[], phases: readonly PhaseSpec[]) {
    setApplying(true);
    setError(null);
    try {
      await bulkAddAgentsAndPhases(
        agents as AgentSpec[],
        phases as PhaseSpec[],
        result?.team_name_suggestion,
        result?.team_description_suggestion,
      );
    } catch (e) {
      setError(String(e));
    } finally {
      setApplying(false);
    }
  }

  // ---- Edit agent ----
  function openEditAgent(agent: AgentSpec, index: number) {
    setEditAgent(agent);
    setEditIndex(index);
    setEditForm({
      name: agent.name,
      description: agent.description,
      system_prompt: agent.system_prompt,
    });
  }

  function saveEditAgent() {
    if (!editAgent || !result) return;
    const updated: AgentSpec = {
      ...editAgent,
      name: editForm.name,
      description: editForm.description,
      system_prompt: editForm.system_prompt,
    };
    const newAgents = [...result.agents];
    const existing = newAgents[editIndex] as RecommendedAgent | undefined;
    if (!existing) return;
    newAgents[editIndex] = { agent: updated, confidence: existing.confidence, reason: existing.reason };
    setResult({ ...result, agents: newAgents });
    setEditAgent(null);
  }

  function copyToClipboard(text: string) {
    navigator.clipboard.writeText(text);
  }

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">AI Workflow Recommender</h1>
        <p className="text-sm text-gray-500 mt-1">
          Get agent and phase suggestions based on your project description or existing codebase.
        </p>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-gray-200">
        <button
          onClick={() => { setTab("greenfield"); setResult(null); setError(null); }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "greenfield"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Greenfield
        </button>
        <button
          onClick={() => { setTab("codebase"); setResult(null); setError(null); }}
          className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
            tab === "codebase"
              ? "border-indigo-600 text-indigo-600"
              : "border-transparent text-gray-500 hover:text-gray-700"
          }`}
        >
          Existing Codebase
        </button>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 px-4 py-3 rounded-md text-sm">
          {error}
        </div>
      )}

      {/* Greenfield Tab */}
      {tab === "greenfield" && !result && (
        <div className="bg-white rounded-lg shadow p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Project Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="e.g., REST API with React frontend, PostgreSQL, CI/CD pipeline, comprehensive testing..."
              rows={4}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
            />
          </div>
          <button
            onClick={handleGreenfield}
            disabled={!description.trim() || loading}
            className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? "Analyzing..." : "Get Recommendations"}
          </button>
        </div>
      )}

      {/* Codebase Tab */}
      {tab === "codebase" && !result && (
        <div className="space-y-4">
          {/* Step 1: Generate prompt */}
          <div className="bg-white rounded-lg shadow p-6 space-y-4">
            <h3 className="text-md font-semibold text-gray-800">
              Step 1: Generate Analysis Prompt
            </h3>
            <p className="text-sm text-gray-500">
              Optionally provide a project description for more targeted analysis.
            </p>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="(Optional) Brief project description or focus areas..."
              rows={2}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
            <button
              onClick={handleGeneratePrompt}
              disabled={promptLoading}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50"
            >
              {promptLoading ? "Generating..." : "Generate Analysis Prompt"}
            </button>
          </div>

          {/* Generated prompt display */}
          {generatedPrompt && (
            <div className="bg-white rounded-lg shadow p-6 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-md font-semibold text-gray-800">
                  Step 2: Copy & Run in Your Coding Assistant
                </h3>
                <button
                  onClick={() => copyToClipboard(generatedPrompt.prompt)}
                  className="px-3 py-1 text-xs bg-gray-100 text-gray-700 rounded hover:bg-gray-200"
                >
                  Copy Prompt
                </button>
              </div>
              <div className="bg-gray-50 rounded-md p-4 text-xs font-mono overflow-auto max-h-48 whitespace-pre-wrap">
                {generatedPrompt.prompt}
              </div>
              <div className="text-sm text-gray-500 whitespace-pre-line">
                {generatedPrompt.instructions}
              </div>
            </div>
          )}

          {/* Step 3: Paste JSON */}
          <div className="bg-white rounded-lg shadow p-6 space-y-4">
            <h3 className="text-md font-semibold text-gray-800">
              {generatedPrompt ? "Step 3" : "Step 2"}: Paste Analysis JSON
            </h3>
            <textarea
              value={codebaseJson}
              onChange={(e) => setCodebaseJson(e.target.value)}
              placeholder='Paste the JSON output from your coding assistant here...'
              rows={8}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
            />
            <button
              onClick={handleAnalyzeCodebase}
              disabled={!codebaseJson.trim() || loading}
              className="px-4 py-2 bg-indigo-600 text-white text-sm font-medium rounded-md hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {loading ? "Analyzing..." : "Analyze"}
            </button>
          </div>
        </div>
      )}

      {/* Results */}
      {result && (
        <div className="space-y-4">
          <button
            onClick={() => setResult(null)}
            className="text-sm text-indigo-600 hover:text-indigo-800"
          >
            &larr; Back to input
          </button>
          <RecommendReviewPanel
            result={result}
            onApply={handleApply}
            onEditAgent={openEditAgent}
            applying={applying}
          />
          {!team && result.agents.length > 0 && (
            <p className="text-sm text-gray-500 italic">
              No team is currently loaded. Applying recommendations will create a new team.
            </p>
          )}
        </div>
      )}

      {/* Edit Agent Modal */}
      <Modal
        open={editAgent !== null}
        onClose={() => setEditAgent(null)}
        title="Edit Recommended Agent"
      >
        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Name</label>
            <input
              type="text"
              value={editForm.name}
              onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
            <textarea
              value={editForm.description}
              onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
              rows={2}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">System Prompt</label>
            <textarea
              value={editForm.system_prompt}
              onChange={(e) => setEditForm({ ...editForm, system_prompt: e.target.value })}
              rows={4}
              className="w-full border border-gray-300 rounded-md px-3 py-2 text-sm font-mono"
            />
          </div>
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setEditAgent(null)}
              className="px-3 py-2 text-sm text-gray-700 border border-gray-300 rounded-md hover:bg-gray-50"
            >
              Cancel
            </button>
            <button
              onClick={saveEditAgent}
              className="px-3 py-2 text-sm text-white bg-indigo-600 rounded-md hover:bg-indigo-700"
            >
              Save
            </button>
          </div>
        </div>
      </Modal>
    </div>
  );
}
