-- =============================================================================
-- Agent Orchestrator — PostgreSQL Schema
-- =============================================================================
-- Creates all tables, indexes, and constraints for the agent-orchestrator
-- platform. Organized into three sections:
--   1. Configuration tables (profiles, agents, workflows, governance)
--   2. Runtime tables (work items, pipeline, agent instances)
--   3. Observability tables (audit, reviews, metrics, config history)
--
-- Runs inside the docker-entrypoint-initdb.d flow, so it executes once
-- when the data volume is first initialized.
-- =============================================================================

BEGIN;

-- ---- Extensions ----
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- =============================================================================
-- 1. CONFIGURATION TABLES
-- =============================================================================

-- ---- Settings (workspace-level, one row per workspace) ----

CREATE TABLE settings (
    id              SERIAL PRIMARY KEY,
    active_profile  VARCHAR(128) NOT NULL DEFAULT '',
    log_level       VARCHAR(16)  NOT NULL DEFAULT 'INFO',
    persistence_backend VARCHAR(16) NOT NULL DEFAULT 'postgresql',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_log_level CHECK (
        log_level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
    ),
    CONSTRAINT chk_persistence_backend CHECK (
        persistence_backend IN ('file', 'sqlite', 'postgresql')
    )
);

CREATE TABLE api_keys (
    id          SERIAL PRIMARY KEY,
    settings_id INT          NOT NULL REFERENCES settings(id) ON DELETE CASCADE,
    provider    VARCHAR(64)  NOT NULL,
    api_key     VARCHAR(512) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_api_keys_provider UNIQUE (settings_id, provider)
);

CREATE TABLE llm_endpoints (
    id          SERIAL PRIMARY KEY,
    settings_id INT          NOT NULL REFERENCES settings(id) ON DELETE CASCADE,
    provider    VARCHAR(64)  NOT NULL,
    endpoint    VARCHAR(512) NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_llm_endpoints_provider UNIQUE (settings_id, provider)
);

-- ---- Profiles ----

CREATE TABLE profiles (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(128) NOT NULL UNIQUE,
    description TEXT         NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ---- Agents ----

CREATE TABLE agents (
    id            SERIAL PRIMARY KEY,
    profile_id    INT          NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    agent_id      VARCHAR(128) NOT NULL,
    name          VARCHAR(256) NOT NULL,
    description   TEXT         NOT NULL DEFAULT '',
    system_prompt TEXT         NOT NULL,
    skills        TEXT[]       NOT NULL DEFAULT '{}',
    phases        TEXT[]       NOT NULL DEFAULT '{}',
    concurrency   INT          NOT NULL DEFAULT 1,
    enabled       BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_agents_profile_agent UNIQUE (profile_id, agent_id),
    CONSTRAINT chk_concurrency CHECK (concurrency BETWEEN 1 AND 100)
);

CREATE TABLE agent_llm_configs (
    id          SERIAL PRIMARY KEY,
    agent_id    INT          NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    provider    VARCHAR(64)  NOT NULL,
    model       VARCHAR(128) NOT NULL,
    temperature NUMERIC(3,2) NOT NULL DEFAULT 0.30,
    max_tokens  INT          NOT NULL DEFAULT 4000,
    endpoint    VARCHAR(512),

    CONSTRAINT uq_agent_llm UNIQUE (agent_id),
    CONSTRAINT chk_temperature CHECK (temperature BETWEEN 0.00 AND 2.00),
    CONSTRAINT chk_max_tokens CHECK (max_tokens BETWEEN 1 AND 200000)
);

CREATE TABLE agent_retry_policies (
    id                  SERIAL PRIMARY KEY,
    agent_id            INT          NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    max_retries         INT          NOT NULL DEFAULT 3,
    delay_seconds       NUMERIC(6,2) NOT NULL DEFAULT 1.00,
    backoff_multiplier  NUMERIC(4,2) NOT NULL DEFAULT 2.00,

    CONSTRAINT uq_agent_retry UNIQUE (agent_id)
);

-- ---- Workflows ----

CREATE TABLE workflows (
    id          SERIAL PRIMARY KEY,
    profile_id  INT          NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name        VARCHAR(256) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_workflow_profile UNIQUE (profile_id)
);

CREATE TABLE workflow_statuses (
    id              SERIAL PRIMARY KEY,
    workflow_id     INT          NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    status_id       VARCHAR(128) NOT NULL,
    name            VARCHAR(256) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    is_initial      BOOLEAN      NOT NULL DEFAULT FALSE,
    is_terminal     BOOLEAN      NOT NULL DEFAULT FALSE,
    transitions_to  TEXT[]       NOT NULL DEFAULT '{}',
    display_order   INT          NOT NULL DEFAULT 0,

    CONSTRAINT uq_workflow_status UNIQUE (workflow_id, status_id)
);

CREATE TABLE workflow_phases (
    id              SERIAL PRIMARY KEY,
    workflow_id     INT          NOT NULL REFERENCES workflows(id) ON DELETE CASCADE,
    phase_id        VARCHAR(128) NOT NULL,
    name            VARCHAR(256) NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',
    phase_order     INT          NOT NULL,
    agents          TEXT[]       NOT NULL DEFAULT '{}',
    parallel        BOOLEAN      NOT NULL DEFAULT FALSE,
    on_success      VARCHAR(128) NOT NULL DEFAULT '',
    on_failure      VARCHAR(128) NOT NULL DEFAULT '',
    skippable       BOOLEAN      NOT NULL DEFAULT FALSE,
    skip            BOOLEAN      NOT NULL DEFAULT FALSE,
    is_terminal     BOOLEAN      NOT NULL DEFAULT FALSE,
    requires_human  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_workflow_phase UNIQUE (workflow_id, phase_id)
);

CREATE TABLE phase_conditions (
    id              SERIAL PRIMARY KEY,
    phase_id        INT          NOT NULL REFERENCES workflow_phases(id) ON DELETE CASCADE,
    condition_type  VARCHAR(8)   NOT NULL,
    expression      TEXT         NOT NULL,
    description     TEXT         NOT NULL DEFAULT '',

    CONSTRAINT chk_condition_type CHECK (condition_type IN ('entry', 'exit'))
);

CREATE TABLE quality_gates (
    id          SERIAL PRIMARY KEY,
    phase_id    INT          NOT NULL REFERENCES workflow_phases(id) ON DELETE CASCADE,
    name        VARCHAR(256) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    on_failure  VARCHAR(16)  NOT NULL DEFAULT 'block',

    CONSTRAINT chk_on_failure CHECK (on_failure IN ('block', 'warn', 'skip'))
);

CREATE TABLE quality_gate_conditions (
    id          SERIAL PRIMARY KEY,
    gate_id     INT  NOT NULL REFERENCES quality_gates(id) ON DELETE CASCADE,
    expression  TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT ''
);

-- ---- Work Item Types ----

CREATE TABLE work_item_types (
    id          SERIAL PRIMARY KEY,
    profile_id  INT          NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    type_id     VARCHAR(128) NOT NULL,
    name        VARCHAR(256) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_work_item_type UNIQUE (profile_id, type_id)
);

CREATE TABLE work_item_type_fields (
    id                SERIAL PRIMARY KEY,
    work_item_type_id INT          NOT NULL REFERENCES work_item_types(id) ON DELETE CASCADE,
    name              VARCHAR(128) NOT NULL,
    field_type        VARCHAR(16)  NOT NULL,
    required          BOOLEAN      NOT NULL DEFAULT FALSE,
    default_value     TEXT,
    enum_values       TEXT[],

    CONSTRAINT chk_field_type CHECK (
        field_type IN ('text', 'string', 'integer', 'float', 'enum', 'boolean')
    )
);

CREATE TABLE artifact_types (
    id                SERIAL PRIMARY KEY,
    work_item_type_id INT          NOT NULL REFERENCES work_item_types(id) ON DELETE CASCADE,
    artifact_type_id  VARCHAR(128) NOT NULL,
    name              VARCHAR(256) NOT NULL,
    description       TEXT         NOT NULL DEFAULT '',
    file_extensions   TEXT[]       NOT NULL DEFAULT '{}'
);

-- ---- Governance ----

CREATE TABLE governance_configs (
    id                      SERIAL PRIMARY KEY,
    profile_id              INT          NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    auto_approve_threshold  NUMERIC(4,3) NOT NULL DEFAULT 0.800,
    review_threshold        NUMERIC(4,3) NOT NULL DEFAULT 0.500,
    abort_threshold         NUMERIC(4,3) NOT NULL DEFAULT 0.200,

    CONSTRAINT uq_governance_profile UNIQUE (profile_id),
    CONSTRAINT chk_thresholds CHECK (
        auto_approve_threshold >= review_threshold
        AND review_threshold >= abort_threshold
    )
);

CREATE TABLE governance_work_type_overrides (
    id              SERIAL PRIMARY KEY,
    governance_id   INT          NOT NULL REFERENCES governance_configs(id) ON DELETE CASCADE,
    work_type       VARCHAR(128) NOT NULL,
    auto_approve_threshold NUMERIC(4,3),
    review_threshold       NUMERIC(4,3),
    abort_threshold        NUMERIC(4,3),

    CONSTRAINT uq_gov_work_type UNIQUE (governance_id, work_type)
);

CREATE TABLE governance_policies (
    id          SERIAL PRIMARY KEY,
    profile_id  INT          NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    policy_id   VARCHAR(128) NOT NULL,
    name        VARCHAR(256) NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    scope       VARCHAR(64)  NOT NULL DEFAULT 'global',
    action      VARCHAR(16)  NOT NULL,
    conditions  TEXT[]       NOT NULL DEFAULT '{}',
    priority    INT          NOT NULL DEFAULT 0,
    enabled     BOOLEAN      NOT NULL DEFAULT TRUE,
    tags        TEXT[]       NOT NULL DEFAULT '{}',

    CONSTRAINT uq_governance_policy UNIQUE (profile_id, policy_id),
    CONSTRAINT chk_policy_action CHECK (
        action IN ('allow', 'deny', 'review', 'warn', 'escalate')
    )
);


-- =============================================================================
-- 2. RUNTIME TABLES
-- =============================================================================

-- ---- Work Items ----

CREATE TABLE work_items (
    id              SERIAL PRIMARY KEY,
    work_item_id    VARCHAR(256) NOT NULL UNIQUE,
    profile_id      INT          NOT NULL REFERENCES profiles(id),
    type_id         VARCHAR(128) NOT NULL,
    title           VARCHAR(512) NOT NULL,
    data            JSONB        NOT NULL DEFAULT '{}',
    priority        INT          NOT NULL DEFAULT 5,
    status          VARCHAR(32)  NOT NULL DEFAULT 'pending',
    current_phase   VARCHAR(128) NOT NULL DEFAULT '',
    submitted_at    TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    metadata        JSONB        NOT NULL DEFAULT '{}',
    results         JSONB        NOT NULL DEFAULT '{}',
    error           TEXT,
    attempt_count   INT          NOT NULL DEFAULT 0,

    CONSTRAINT chk_priority CHECK (priority BETWEEN 0 AND 10),
    CONSTRAINT chk_work_item_status CHECK (
        status IN ('pending', 'queued', 'in_progress', 'completed', 'failed', 'cancelled')
    )
);

CREATE INDEX idx_work_items_status ON work_items(status);
CREATE INDEX idx_work_items_profile ON work_items(profile_id);
CREATE INDEX idx_work_items_type ON work_items(type_id);
CREATE INDEX idx_work_items_priority ON work_items(priority, submitted_at);

-- ---- Pipeline Entries ----

CREATE TABLE pipeline_entries (
    id                SERIAL PRIMARY KEY,
    work_item_id      INT          NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    current_phase_id  VARCHAR(128) NOT NULL,
    locked            BOOLEAN      NOT NULL DEFAULT FALSE,
    locked_by         VARCHAR(256),
    phase_attempts    JSONB        NOT NULL DEFAULT '{}',
    entered_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT uq_pipeline_work_item UNIQUE (work_item_id)
);

CREATE TABLE phase_history (
    id                SERIAL PRIMARY KEY,
    pipeline_entry_id INT          NOT NULL REFERENCES pipeline_entries(id) ON DELETE CASCADE,
    phase_id          VARCHAR(128) NOT NULL,
    result            VARCHAR(16)  NOT NULL,
    started_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at      TIMESTAMPTZ,
    details           JSONB        NOT NULL DEFAULT '{}',

    CONSTRAINT chk_phase_result CHECK (result IN ('success', 'failure', 'skipped'))
);

CREATE INDEX idx_phase_history_entry ON phase_history(pipeline_entry_id);

-- ---- Agent Instances ----

CREATE TABLE agent_instances (
    id                  SERIAL PRIMARY KEY,
    instance_id         VARCHAR(256) NOT NULL UNIQUE,
    agent_def_id        INT          NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    state               VARCHAR(16)  NOT NULL DEFAULT 'idle',
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_active         TIMESTAMPTZ,
    tasks_completed     INT          NOT NULL DEFAULT 0,
    current_work_item_id INT         REFERENCES work_items(id) ON DELETE SET NULL,

    CONSTRAINT chk_agent_state CHECK (
        state IN ('idle', 'running', 'error', 'shutdown')
    )
);

CREATE INDEX idx_agent_instances_state ON agent_instances(state);
CREATE INDEX idx_agent_instances_def ON agent_instances(agent_def_id);


-- =============================================================================
-- 3. OBSERVABILITY TABLES
-- =============================================================================

-- ---- Review Queue ----

CREATE TABLE review_items (
    id              SERIAL PRIMARY KEY,
    review_id       VARCHAR(128) NOT NULL UNIQUE,
    work_item_id    INT          NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    phase_id        VARCHAR(128) NOT NULL,
    reason          TEXT         NOT NULL,
    context         JSONB        NOT NULL DEFAULT '{}',
    decision_data   JSONB        NOT NULL DEFAULT '{}',
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    reviewed        BOOLEAN      NOT NULL DEFAULT FALSE,
    reviewed_by     VARCHAR(256),
    reviewed_at     TIMESTAMPTZ,
    review_notes    TEXT         NOT NULL DEFAULT ''
);

CREATE INDEX idx_review_items_pending ON review_items(reviewed) WHERE NOT reviewed;
CREATE INDEX idx_review_items_work ON review_items(work_item_id);

-- ---- Governance Decisions ----

CREATE TABLE governance_decisions (
    id              SERIAL PRIMARY KEY,
    work_item_id    INT          NOT NULL REFERENCES work_items(id) ON DELETE CASCADE,
    resolution      VARCHAR(32)  NOT NULL,
    confidence      NUMERIC(4,3) NOT NULL,
    policy_id       VARCHAR(128),
    policy_name     VARCHAR(256),
    reason          TEXT         NOT NULL,
    warnings        TEXT[]       NOT NULL DEFAULT '{}',
    decided_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_resolution CHECK (
        resolution IN ('allow', 'allow_with_warning', 'queue_for_review', 'abort')
    )
);

CREATE INDEX idx_gov_decisions_work ON governance_decisions(work_item_id);

-- ---- Audit Records (hash-chained) ----

CREATE TABLE audit_records (
    id          SERIAL PRIMARY KEY,
    sequence    INT          NOT NULL,
    record_type VARCHAR(32)  NOT NULL,
    action      VARCHAR(256) NOT NULL,
    summary     TEXT         NOT NULL,
    work_id     VARCHAR(256) NOT NULL DEFAULT '',
    agent_id    VARCHAR(256) NOT NULL DEFAULT '',
    data        JSONB        NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    prev_hash   VARCHAR(16)  NOT NULL DEFAULT '',
    hash        VARCHAR(16)  NOT NULL,

    CONSTRAINT chk_record_type CHECK (
        record_type IN (
            'decision', 'state_change', 'escalation',
            'error', 'config_change', 'system_event'
        )
    )
);

CREATE INDEX idx_audit_work ON audit_records(work_id);
CREATE INDEX idx_audit_type ON audit_records(record_type);
CREATE INDEX idx_audit_sequence ON audit_records(sequence);

-- ---- Metrics ----

CREATE TABLE metrics (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(256) NOT NULL,
    value       NUMERIC      NOT NULL,
    tags        JSONB        NOT NULL DEFAULT '{}',
    recorded_at TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_metrics_name ON metrics(name);
CREATE INDEX idx_metrics_time ON metrics(recorded_at);

-- ---- Domain Catalogs (AI Workflow Recommender) ----

CREATE TABLE domain_catalogs (
    domain      VARCHAR(128) PRIMARY KEY,
    data        JSONB        NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

-- ---- Config History ----

CREATE TABLE config_history (
    id          SERIAL PRIMARY KEY,
    file_path   VARCHAR(512) NOT NULL,
    snapshot    JSONB        NOT NULL,
    description TEXT         NOT NULL DEFAULT '',
    changed_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_config_history_path ON config_history(file_path);
CREATE INDEX idx_config_history_time ON config_history(changed_at DESC);


-- =============================================================================
-- Trigger: auto-update updated_at on configuration tables
-- =============================================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_settings_updated
    BEFORE UPDATE ON settings FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_profiles_updated
    BEFORE UPDATE ON profiles FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_agents_updated
    BEFORE UPDATE ON agents FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_workflows_updated
    BEFORE UPDATE ON workflows FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_workflow_phases_updated
    BEFORE UPDATE ON workflow_phases FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_work_item_types_updated
    BEFORE UPDATE ON work_item_types FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_domain_catalogs_updated
    BEFORE UPDATE ON domain_catalogs FOR EACH ROW EXECUTE FUNCTION update_updated_at();

COMMIT;
