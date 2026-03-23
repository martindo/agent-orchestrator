/**
 * TypeScript type definitions matching the Studio IR models.
 * These mirror the Python Pydantic models in studio/ir/models.py.
 */

export interface LLMSpec {
  readonly provider: string;
  readonly model: string;
  readonly temperature: number;
  readonly max_tokens: number;
  readonly endpoint: string | null;
}

export interface RetryPolicySpec {
  readonly max_retries: number;
  readonly delay_seconds: number;
  readonly backoff_multiplier: number;
}

export interface ConditionSpec {
  readonly expression: string;
  readonly description: string;
}

export interface QualityGateSpec {
  readonly name: string;
  readonly description: string;
  readonly conditions: readonly ConditionSpec[];
  readonly on_failure: "block" | "warn" | "skip";
}

export interface AgentSpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly system_prompt: string;
  readonly skills: readonly string[];
  readonly phases: readonly string[];
  readonly llm: LLMSpec;
  readonly concurrency: number;
  readonly retry_policy: RetryPolicySpec;
  readonly enabled: boolean;
}

export interface StatusSpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly is_initial: boolean;
  readonly is_terminal: boolean;
  readonly transitions_to: readonly string[];
}

export interface PhaseSpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly order: number;
  readonly agents: readonly string[];
  readonly parallel: boolean;
  readonly entry_conditions: readonly ConditionSpec[];
  readonly exit_conditions: readonly ConditionSpec[];
  readonly quality_gates: readonly QualityGateSpec[];
  readonly critic_agent: string | null;
  readonly critic_rubric: string;
  readonly max_phase_retries: number;
  readonly retry_backoff_seconds: number;
  readonly on_success: string;
  readonly on_failure: string;
  readonly skippable: boolean;
  readonly skip: boolean;
  readonly is_terminal: boolean;
  readonly requires_human: boolean;
  readonly required_capabilities: readonly string[];
  readonly expected_output_fields: readonly string[];
}

export interface WorkflowSpec {
  readonly name: string;
  readonly description: string;
  readonly statuses: readonly StatusSpec[];
  readonly phases: readonly PhaseSpec[];
}

export interface DelegatedAuthoritySpec {
  readonly auto_approve_threshold: number;
  readonly review_threshold: number;
  readonly abort_threshold: number;
  readonly work_type_overrides: Record<string, Record<string, number>>;
}

export interface PolicySpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly scope: string;
  readonly action: string;
  readonly conditions: readonly string[];
  readonly priority: number;
  readonly enabled: boolean;
  readonly tags: readonly string[];
}

export interface GovernanceSpec {
  readonly delegated_authority: DelegatedAuthoritySpec;
  readonly policies: readonly PolicySpec[];
}

export interface WorkItemFieldSpec {
  readonly name: string;
  readonly type: "text" | "string" | "integer" | "float" | "enum" | "boolean";
  readonly required: boolean;
  readonly default: unknown;
  readonly values: readonly string[] | null;
}

export interface ArtifactTypeSpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly file_extensions: readonly string[];
}

export interface WorkItemTypeSpec {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly custom_fields: readonly WorkItemFieldSpec[];
  readonly artifact_types: readonly ArtifactTypeSpec[];
}

export interface TeamSpec {
  readonly name: string;
  readonly description: string;
  readonly agents: readonly AgentSpec[];
  readonly workflow: WorkflowSpec;
  readonly governance: GovernanceSpec;
  readonly work_item_types: readonly WorkItemTypeSpec[];
  readonly manifest: Record<string, unknown> | null;
}

export interface ValidationMessage {
  readonly message: string;
  readonly path: string;
  readonly severity: "error" | "warning";
}

export interface ValidationResult {
  readonly is_valid: boolean;
  readonly errors: readonly ValidationMessage[];
  readonly warnings: readonly ValidationMessage[];
  readonly error_count: number;
  readonly warning_count: number;
}

export interface GraphNode {
  readonly phase_id: string;
  readonly name: string;
  readonly is_terminal: boolean;
  readonly order: number;
  readonly agent_count: number;
}

export interface GraphEdge {
  readonly from_phase: string;
  readonly to_phase: string;
  readonly trigger: string;
}

export interface GraphResult {
  readonly is_valid: boolean;
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  readonly errors: readonly string[];
  readonly warnings: readonly string[];
  readonly orphan_phases: readonly string[];
}

export interface TemplateInfo {
  readonly name: string;
  readonly path: string;
}
