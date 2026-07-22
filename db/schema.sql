-- =============================================================================
-- Agent Orchestrator -- SQL persistence schema (postgresql)
-- =============================================================================
-- GENERATED from agent_orchestrator/persistence/sql/tables.py -- do not edit by
-- hand. Regenerate with:
--   python -m agent_orchestrator.persistence.sql.schema postgresql > db/schema.sql
-- The application also creates these tables on startup via metadata.create_all,
-- so applying this file is optional (it exists for review and ops).
-- =============================================================================

CREATE TABLE ao_artifacts (
	row_id SERIAL NOT NULL, 
	artifact_id VARCHAR(64) NOT NULL, 
	work_id VARCHAR(128) NOT NULL, 
	phase_id VARCHAR(128) NOT NULL, 
	agent_id VARCHAR(128) NOT NULL, 
	artifact_type VARCHAR(64) NOT NULL, 
	content_hash VARCHAR(64) NOT NULL, 
	version INTEGER NOT NULL, 
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL, 
	run_id VARCHAR(128) NOT NULL, 
	app_id VARCHAR(128) NOT NULL, 
	content JSON NOT NULL, 
	PRIMARY KEY (row_id)
);

CREATE INDEX ix_ao_artifacts_artifact_type ON ao_artifacts (artifact_type);

CREATE INDEX ix_ao_artifacts_content_hash ON ao_artifacts (content_hash);

CREATE INDEX ix_ao_artifacts_timestamp ON ao_artifacts (timestamp);

CREATE INDEX ix_ao_artifacts_work_id ON ao_artifacts (work_id);

CREATE TABLE ao_state (
	namespace VARCHAR(256) NOT NULL, 
	data JSON NOT NULL, 
	updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	PRIMARY KEY (namespace)
);

CREATE TABLE ao_work_items (
	id VARCHAR(128) NOT NULL, 
	type_id VARCHAR(128) NOT NULL, 
	app_id VARCHAR(128) NOT NULL, 
	run_id VARCHAR(128) NOT NULL, 
	status VARCHAR(32) NOT NULL, 
	submitted_at TIMESTAMP WITH TIME ZONE NOT NULL, 
	payload JSON NOT NULL, 
	PRIMARY KEY (id)
);

CREATE INDEX ix_ao_work_items_app ON ao_work_items (app_id);

CREATE INDEX ix_ao_work_items_run ON ao_work_items (run_id);

CREATE INDEX ix_ao_work_items_status ON ao_work_items (status);

CREATE INDEX ix_ao_work_items_submitted_at ON ao_work_items (submitted_at);

CREATE INDEX ix_ao_work_items_type ON ao_work_items (type_id);
