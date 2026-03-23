/**
 * Studio API client — typed fetch wrappers for all backend endpoints.
 */

import type {
  TeamSpec,
  AgentSpec,
  PhaseSpec,
  ValidationResult,
  GraphResult,
  TemplateInfo,
} from "../types";

const BASE = "/api/studio";

async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(`API ${response.status}: ${text}`);
  }

  return response.json() as Promise<T>;
}

// ---- Health ----

interface HealthResponse {
  status: string;
  version: string;
  team_loaded: boolean;
  team_name: string | null;
  runtime_url: string;
}

export function getHealth(): Promise<HealthResponse> {
  return request<HealthResponse>("/health");
}

// ---- Teams ----

export function createTeam(name: string, description: string = ""): Promise<TeamSpec> {
  return request<TeamSpec>("/teams", {
    method: "POST",
    body: JSON.stringify({ name, description }),
  });
}

export function getCurrentTeam(): Promise<TeamSpec> {
  return request<TeamSpec>("/teams/current");
}

export function updateCurrentTeam(team: TeamSpec): Promise<TeamSpec> {
  return request<TeamSpec>("/teams/current", {
    method: "PUT",
    body: JSON.stringify(team),
  });
}

export function importFromTemplate(templatePath: string): Promise<TeamSpec> {
  return request<TeamSpec>("/teams/from-template", {
    method: "POST",
    body: JSON.stringify({ template_path: templatePath }),
  });
}

// ---- Templates ----

interface TemplateListResponse {
  templates: TemplateInfo[];
  count: number;
  profiles_dir: string;
}

export function listTemplates(): Promise<TemplateListResponse> {
  return request<TemplateListResponse>("/templates");
}

export function importTemplate(
  templateName?: string,
  templatePath?: string,
): Promise<TeamSpec> {
  return request<TeamSpec>("/templates/import", {
    method: "POST",
    body: JSON.stringify({
      template_name: templateName ?? null,
      template_path: templatePath ?? null,
    }),
  });
}

interface ExportResponse {
  output_dir: string;
  files: string[];
  count: number;
}

export function exportTemplate(
  outputName?: string,
  outputPath?: string,
): Promise<ExportResponse> {
  return request<ExportResponse>("/templates/export", {
    method: "POST",
    body: JSON.stringify({
      output_name: outputName ?? null,
      output_path: outputPath ?? null,
    }),
  });
}

// ---- Validation ----

export function validateTeam(): Promise<ValidationResult> {
  return request<ValidationResult>("/validate", { method: "POST" });
}

export function validateViaRuntime(): Promise<ValidationResult> {
  return request<ValidationResult>("/validate/runtime", { method: "POST" });
}

interface ConditionValidateResponse {
  expression: string;
  is_valid: boolean;
  errors: string[];
}

export function validateCondition(expression: string): Promise<ConditionValidateResponse> {
  return request<ConditionValidateResponse>("/validate/condition", {
    method: "POST",
    body: JSON.stringify({ expression }),
  });
}

// ---- Preview / Generation ----

export function previewAll(): Promise<Record<string, string>> {
  return request<Record<string, string>>("/preview");
}

export function previewComponent(component: string): Promise<{ filename: string; content: string }> {
  return request<{ filename: string; content: string }>(`/preview/${component}`);
}

// ---- Graph ----

export function getGraph(): Promise<GraphResult> {
  return request<GraphResult>("/graph");
}

export function validateGraph(): Promise<GraphResult> {
  return request<GraphResult>("/graph/validate", { method: "POST" });
}

// ---- Conditions ----

interface OperatorsResponse {
  operators: string[];
  descriptions: Record<string, string>;
}

export function getOperators(): Promise<OperatorsResponse> {
  return request<OperatorsResponse>("/conditions/operators");
}

interface BuildConditionResponse {
  expression: string;
  field: string;
  operator: string;
  value: string;
}

export function buildCondition(
  field: string,
  operator: string,
  value: string,
): Promise<BuildConditionResponse> {
  return request<BuildConditionResponse>("/conditions/build", {
    method: "POST",
    body: JSON.stringify({ field, operator, value }),
  });
}

interface ParseConditionResponse {
  expression: string;
  field: string;
  operator: string;
  value: string;
}

export function parseCondition(expression: string): Promise<ParseConditionResponse> {
  return request<ParseConditionResponse>("/conditions/parse", {
    method: "POST",
    body: JSON.stringify({ expression }),
  });
}

// ---- Deploy ----

interface DeployResponse {
  success: boolean;
  profile_dir: string;
  files_written: string[];
  runtime_reloaded: boolean;
  errors: string[];
  warnings: string[];
}

export function deploy(options: {
  profile_name?: string;
  validate_first?: boolean;
  trigger_reload?: boolean;
  force?: boolean;
} = {}): Promise<DeployResponse> {
  return request<DeployResponse>("/deploy", {
    method: "POST",
    body: JSON.stringify(options),
  });
}

// ---- Extensions ----

interface StubResponse {
  code: string;
  written: boolean;
  path?: string;
}

export function generateConnectorStub(
  providerId: string,
  displayName: string,
  capability: string = "EXTERNAL_API",
): Promise<StubResponse> {
  return request<StubResponse>("/extensions/connector", {
    method: "POST",
    body: JSON.stringify({
      provider_id: providerId,
      display_name: displayName,
      capability,
    }),
  });
}

export function generateEventHandlerStub(
  handlerName: string,
  eventTypes?: string[],
): Promise<StubResponse> {
  return request<StubResponse>("/extensions/event-handler", {
    method: "POST",
    body: JSON.stringify({
      handler_name: handlerName,
      event_types: eventTypes ?? null,
    }),
  });
}

export function generateHookStub(
  phaseId: string,
  hookName?: string,
): Promise<StubResponse> {
  return request<StubResponse>("/extensions/hook", {
    method: "POST",
    body: JSON.stringify({
      phase_id: phaseId,
      hook_name: hookName ?? null,
    }),
  });
}

// ---- Prompts ----

interface PromptPackResponse {
  prompts: Record<string, string>;
  written: string[];
  count: number;
  output_dir: string;
}

export function generatePromptPack(
  outputDir?: string,
  includeConnector?: string,
): Promise<PromptPackResponse> {
  return request<PromptPackResponse>("/prompts/generate", {
    method: "POST",
    body: JSON.stringify({
      output_dir: outputDir ?? null,
      include_connector: includeConnector ?? null,
    }),
  });
}

// ---- Connectors ----

interface ConnectorListResponse {
  providers: Array<{
    provider_id: string;
    display_name: string;
    capability_types: string[];
    operations: Array<{
      operation: string;
      description: string;
    }>;
    enabled: boolean;
    auth_required: boolean;
  }>;
  count: number;
}

export function discoverConnectors(): Promise<ConnectorListResponse> {
  return request<ConnectorListResponse>("/connectors");
}

// ---- Recommend ----

export interface RecommendedAgent {
  agent: AgentSpec;
  confidence: number;
  reason: string;
}

export interface RecommendedPhase {
  phase: PhaseSpec;
  confidence: number;
  reason: string;
}

export interface RecommendationResult {
  agents: RecommendedAgent[];
  phases: RecommendedPhase[];
  team_name_suggestion: string;
  team_description_suggestion: string;
  source: string;
}

export function recommendGreenfield(description: string): Promise<RecommendationResult> {
  return request<RecommendationResult>("/recommend/greenfield", {
    method: "POST",
    body: JSON.stringify({ description }),
  });
}

export function recommendCodebasePrompt(
  projectDescription?: string,
  focusAreas?: string[],
): Promise<{ prompt: string; instructions: string }> {
  return request<{ prompt: string; instructions: string }>("/recommend/codebase-prompt", {
    method: "POST",
    body: JSON.stringify({
      project_description: projectDescription ?? null,
      focus_areas: focusAreas ?? [],
    }),
  });
}

export function recommendFromCodebase(
  analysis: Record<string, unknown>,
): Promise<RecommendationResult> {
  return request<RecommendationResult>("/recommend/from-codebase", {
    method: "POST",
    body: JSON.stringify({ analysis }),
  });
}

// ---- Schemas ----

export function getAllSchemas(): Promise<Record<string, Record<string, unknown>>> {
  return request<Record<string, Record<string, unknown>>>("/schemas");
}

// ---- Settings ----

export interface ProviderInfo {
  id: string;
  name: string;
  has_key: boolean;
  endpoint: string;
}

export interface SettingsData {
  providers: ProviderInfo[];
}

export function getSettings(): Promise<SettingsData> {
  return request<SettingsData>("/settings");
}

export function updateSettings(updates: {
  api_keys?: Record<string, string>;
  endpoints?: Record<string, string>;
}): Promise<SettingsData> {
  return request<SettingsData>("/settings", {
    method: "PUT",
    body: JSON.stringify(updates),
  });
}

export interface ModelInfo {
  id: string;
  name: string;
}

export interface ModelsForProvider {
  provider: string;
  models: ModelInfo[];
  error: string | null;
}

export function fetchModels(providerId: string): Promise<ModelsForProvider> {
  return request<ModelsForProvider>(`/settings/models/${providerId}`);
}
