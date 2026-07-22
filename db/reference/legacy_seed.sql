-- =============================================================================
-- Agent Orchestrator — Seed Data
-- =============================================================================
-- Inserts a default settings row and the two built-in profiles
-- (content-moderation and software-dev) so the system is usable
-- immediately after first boot.
-- =============================================================================

BEGIN;

-- ---- Default Settings ----

INSERT INTO settings (active_profile, log_level, persistence_backend)
VALUES ('content-moderation', 'INFO', 'postgresql');

-- =============================================================================
-- Profile: content-moderation
-- =============================================================================

INSERT INTO profiles (name, description)
VALUES (
    'content-moderation',
    'Content moderation pipeline with classification, analysis, and review'
);

-- Agents
WITH p AS (SELECT id FROM profiles WHERE name = 'content-moderation')
INSERT INTO agents (profile_id, agent_id, name, description, system_prompt, skills, phases, concurrency)
VALUES
    ((SELECT id FROM p), 'classifier',  'Content Classifier',
     'Classifies incoming content into categories',
     'You are a content classifier. Analyze the submitted content and assign it to one or more categories: safe, nsfw, spam, hate_speech, violence, self_harm, misinformation. Return a JSON object with category scores.',
     ARRAY['classification', 'nlp'], ARRAY['classify'], 3),

    ((SELECT id FROM p), 'analyzer',    'Deep Analyzer',
     'Performs deep analysis on flagged content',
     'You are a deep content analyzer. For content that was flagged by the classifier, perform detailed analysis. Identify specific policy violations, extract context, and assess severity (low, medium, high, critical).',
     ARRAY['analysis', 'nlp'], ARRAY['analyze'], 2),

    ((SELECT id FROM p), 'reviewer',    'Decision Maker',
     'Makes final moderation decisions',
     'You are a content moderation decision maker. Based on the classification and analysis results, make a final moderation decision: approve, flag_for_review, remove, or escalate. Provide clear reasoning.',
     ARRAY['decision_making'], ARRAY['decide'], 1);

-- Agent LLM configs
WITH a AS (
    SELECT ag.id, ag.agent_id
    FROM agents ag
    JOIN profiles p ON ag.profile_id = p.id
    WHERE p.name = 'content-moderation'
)
INSERT INTO agent_llm_configs (agent_id, provider, model, temperature, max_tokens)
VALUES
    ((SELECT id FROM a WHERE agent_id = 'classifier'), 'openai', 'gpt-4o', 0.10, 2000),
    ((SELECT id FROM a WHERE agent_id = 'analyzer'),   'openai', 'gpt-4o', 0.30, 4000),
    ((SELECT id FROM a WHERE agent_id = 'reviewer'),   'anthropic', 'claude-sonnet-4-20250514', 0.20, 4000);

-- Agent retry policies (defaults for all)
WITH a AS (
    SELECT ag.id
    FROM agents ag
    JOIN profiles p ON ag.profile_id = p.id
    WHERE p.name = 'content-moderation'
)
INSERT INTO agent_retry_policies (agent_id, max_retries, delay_seconds, backoff_multiplier)
SELECT id, 3, 1.00, 2.00 FROM a;

-- Workflow
WITH p AS (SELECT id FROM profiles WHERE name = 'content-moderation')
INSERT INTO workflows (profile_id, name, description)
VALUES ((SELECT id FROM p), 'Content Moderation Pipeline', 'Classify → Analyze → Decide → Complete');

-- Workflow statuses
WITH w AS (
    SELECT wf.id FROM workflows wf
    JOIN profiles p ON wf.profile_id = p.id
    WHERE p.name = 'content-moderation'
)
INSERT INTO workflow_statuses (workflow_id, status_id, name, description, is_initial, is_terminal, transitions_to, display_order)
VALUES
    ((SELECT id FROM w), 'pending',     'Pending',     'Awaiting processing',  TRUE,  FALSE, ARRAY['classifying'], 0),
    ((SELECT id FROM w), 'classifying', 'Classifying', 'Content classification in progress', FALSE, FALSE, ARRAY['analyzing', 'completed'], 1),
    ((SELECT id FROM w), 'analyzing',   'Analyzing',   'Deep analysis in progress', FALSE, FALSE, ARRAY['deciding'], 2),
    ((SELECT id FROM w), 'deciding',    'Deciding',    'Moderation decision in progress', FALSE, FALSE, ARRAY['completed', 'escalated'], 3),
    ((SELECT id FROM w), 'completed',   'Completed',   'Processing complete', FALSE, TRUE, ARRAY[]::TEXT[], 4),
    ((SELECT id FROM w), 'escalated',   'Escalated',   'Escalated for human review', FALSE, TRUE, ARRAY[]::TEXT[], 5);

-- Workflow phases
WITH w AS (
    SELECT wf.id FROM workflows wf
    JOIN profiles p ON wf.profile_id = p.id
    WHERE p.name = 'content-moderation'
)
INSERT INTO workflow_phases (workflow_id, phase_id, name, description, phase_order, agents, on_success, on_failure, is_terminal)
VALUES
    ((SELECT id FROM w), 'classify', 'Classification',   'Initial content classification', 1, ARRAY['classifier'], 'analyze', 'complete', FALSE),
    ((SELECT id FROM w), 'analyze',  'Deep Analysis',    'Detailed content analysis',      2, ARRAY['analyzer'],   'decide',  'complete', FALSE),
    ((SELECT id FROM w), 'decide',   'Decision',         'Final moderation decision',      3, ARRAY['reviewer'],   'complete','complete', FALSE),
    ((SELECT id FROM w), 'complete', 'Complete',          'Processing complete',            4, ARRAY[]::TEXT[],     '',        '',         TRUE);

-- Governance
WITH p AS (SELECT id FROM profiles WHERE name = 'content-moderation')
INSERT INTO governance_configs (profile_id, auto_approve_threshold, review_threshold, abort_threshold)
VALUES ((SELECT id FROM p), 0.800, 0.500, 0.200);

-- Governance policies
WITH p AS (SELECT id FROM profiles WHERE name = 'content-moderation')
INSERT INTO governance_policies (profile_id, policy_id, name, description, action, conditions, priority, tags)
VALUES
    ((SELECT id FROM p), 'auto-approve-safe', 'Auto-approve safe content',
     'Content classified as safe with high confidence is auto-approved',
     'allow', ARRAY['confidence >= 0.9'], 10, ARRAY['safety']),

    ((SELECT id FROM p), 'block-critical', 'Block critical violations',
     'Content with critical severity is immediately blocked',
     'deny', ARRAY['severity == ''critical'''], 20, ARRAY['safety', 'critical']);

-- Work item type
WITH p AS (SELECT id FROM profiles WHERE name = 'content-moderation')
INSERT INTO work_item_types (profile_id, type_id, name, description)
VALUES ((SELECT id FROM p), 'content-submission', 'Content Submission', 'User-submitted content for moderation');

WITH wit AS (
    SELECT wit.id FROM work_item_types wit
    JOIN profiles p ON wit.profile_id = p.id
    WHERE p.name = 'content-moderation' AND wit.type_id = 'content-submission'
)
INSERT INTO work_item_type_fields (work_item_type_id, name, field_type, required)
VALUES
    ((SELECT id FROM wit), 'content_text', 'text',    TRUE),
    ((SELECT id FROM wit), 'content_url',  'string',  FALSE),
    ((SELECT id FROM wit), 'source',       'string',  FALSE),
    ((SELECT id FROM wit), 'language',     'string',  FALSE);


-- =============================================================================
-- Profile: software-dev
-- =============================================================================

INSERT INTO profiles (name, description)
VALUES (
    'software-dev',
    'Software development pipeline with planning, implementation, testing, and review'
);

-- Agents
WITH p AS (SELECT id FROM profiles WHERE name = 'software-dev')
INSERT INTO agents (profile_id, agent_id, name, description, system_prompt, skills, phases, concurrency)
VALUES
    ((SELECT id FROM p), 'planner',     'Task Planner',
     'Breaks down tasks into subtasks and estimates',
     'You are a software task planner. Break down the given task into subtasks, estimate effort, identify dependencies, and suggest an implementation order.',
     ARRAY['planning', 'estimation'], ARRAY['plan'], 1),

    ((SELECT id FROM p), 'architect',   'Solution Architect',
     'Designs technical solutions and architecture',
     'You are a solution architect. Design the technical approach for the given task. Consider existing codebase patterns, scalability, and maintainability.',
     ARRAY['architecture', 'design'], ARRAY['plan', 'review'], 1),

    ((SELECT id FROM p), 'coder',       'Code Generator',
     'Writes production code',
     'You are a code generator. Write clean, well-tested production code following the project coding standards. Include type hints, docstrings, and error handling.',
     ARRAY['coding', 'python', 'typescript'], ARRAY['implement'], 3),

    ((SELECT id FROM p), 'tester',      'Test Writer',
     'Creates comprehensive test suites',
     'You are a test engineer. Write comprehensive tests including unit tests, integration tests, and edge cases. Aim for high coverage of business logic.',
     ARRAY['testing', 'pytest'], ARRAY['test'], 2),

    ((SELECT id FROM p), 'reviewer',    'Code Reviewer',
     'Reviews code for quality and standards',
     'You are a code reviewer. Review the submitted code for correctness, performance, security, and adherence to coding standards. Provide actionable feedback.',
     ARRAY['review', 'security'], ARRAY['review'], 1),

    ((SELECT id FROM p), 'doc-writer',  'Documentation Writer',
     'Creates and updates documentation',
     'You are a documentation writer. Create clear, accurate documentation including API docs, user guides, and inline comments.',
     ARRAY['documentation', 'markdown'], ARRAY['document'], 1),

    ((SELECT id FROM p), 'security',    'Security Analyzer',
     'Scans for security vulnerabilities',
     'You are a security analyst. Scan the code for OWASP Top 10 vulnerabilities, insecure patterns, and potential attack vectors. Provide remediation steps.',
     ARRAY['security', 'owasp'], ARRAY['review'], 1),

    ((SELECT id FROM p), 'deployer',    'Deployment Agent',
     'Handles build and deployment tasks',
     'You are a deployment agent. Build the project, run final checks, and prepare deployment artifacts. Verify all tests pass before proceeding.',
     ARRAY['deployment', 'ci_cd'], ARRAY['deploy'], 1);

-- Agent LLM configs
WITH a AS (
    SELECT ag.id, ag.agent_id
    FROM agents ag
    JOIN profiles p ON ag.profile_id = p.id
    WHERE p.name = 'software-dev'
)
INSERT INTO agent_llm_configs (agent_id, provider, model, temperature, max_tokens)
VALUES
    ((SELECT id FROM a WHERE agent_id = 'planner'),    'anthropic', 'claude-sonnet-4-20250514', 0.30, 4000),
    ((SELECT id FROM a WHERE agent_id = 'architect'),  'anthropic', 'claude-sonnet-4-20250514', 0.20, 8000),
    ((SELECT id FROM a WHERE agent_id = 'coder'),      'anthropic', 'claude-sonnet-4-20250514', 0.10, 8000),
    ((SELECT id FROM a WHERE agent_id = 'tester'),     'openai',    'gpt-4o',   0.10, 4000),
    ((SELECT id FROM a WHERE agent_id = 'reviewer'),   'anthropic', 'claude-sonnet-4-20250514', 0.20, 4000),
    ((SELECT id FROM a WHERE agent_id = 'doc-writer'), 'openai',    'gpt-4o',   0.30, 4000),
    ((SELECT id FROM a WHERE agent_id = 'security'),   'anthropic', 'claude-sonnet-4-20250514', 0.10, 4000),
    ((SELECT id FROM a WHERE agent_id = 'deployer'),   'openai',    'gpt-4o',   0.10, 2000);

-- Agent retry policies (defaults for all)
WITH a AS (
    SELECT ag.id
    FROM agents ag
    JOIN profiles p ON ag.profile_id = p.id
    WHERE p.name = 'software-dev'
)
INSERT INTO agent_retry_policies (agent_id, max_retries, delay_seconds, backoff_multiplier)
SELECT id, 3, 1.00, 2.00 FROM a;

-- Workflow
WITH p AS (SELECT id FROM profiles WHERE name = 'software-dev')
INSERT INTO workflows (profile_id, name, description)
VALUES ((SELECT id FROM p), 'Software Development Pipeline', 'Plan → Implement → Test → Review → Document → Deploy');

-- Workflow statuses
WITH w AS (
    SELECT wf.id FROM workflows wf
    JOIN profiles p ON wf.profile_id = p.id
    WHERE p.name = 'software-dev'
)
INSERT INTO workflow_statuses (workflow_id, status_id, name, description, is_initial, is_terminal, transitions_to, display_order)
VALUES
    ((SELECT id FROM w), 'backlog',        'Backlog',        'Not yet started',             TRUE,  FALSE, ARRAY['planning'], 0),
    ((SELECT id FROM w), 'planning',       'Planning',       'Task breakdown and design',   FALSE, FALSE, ARRAY['implementing'], 1),
    ((SELECT id FROM w), 'implementing',   'Implementing',   'Code being written',          FALSE, FALSE, ARRAY['testing'], 2),
    ((SELECT id FROM w), 'testing',        'Testing',        'Tests being written and run',  FALSE, FALSE, ARRAY['reviewing', 'implementing'], 3),
    ((SELECT id FROM w), 'reviewing',      'Reviewing',      'Code review in progress',     FALSE, FALSE, ARRAY['documenting', 'implementing'], 4),
    ((SELECT id FROM w), 'documenting',    'Documenting',    'Documentation being written', FALSE, FALSE, ARRAY['deploying'], 5),
    ((SELECT id FROM w), 'deploying',      'Deploying',      'Deployment in progress',      FALSE, FALSE, ARRAY['done', 'implementing'], 6),
    ((SELECT id FROM w), 'done',           'Done',           'Task complete',               FALSE, TRUE,  ARRAY[]::TEXT[], 7),
    ((SELECT id FROM w), 'blocked',        'Blocked',        'Blocked on external dependency', FALSE, TRUE, ARRAY[]::TEXT[], 8);

-- Workflow phases
WITH w AS (
    SELECT wf.id FROM workflows wf
    JOIN profiles p ON wf.profile_id = p.id
    WHERE p.name = 'software-dev'
)
INSERT INTO workflow_phases (workflow_id, phase_id, name, description, phase_order, agents, parallel, on_success, on_failure, is_terminal)
VALUES
    ((SELECT id FROM w), 'plan',      'Planning',       'Task breakdown and architecture',    1, ARRAY['planner', 'architect'], TRUE,  'implement', 'complete', FALSE),
    ((SELECT id FROM w), 'implement', 'Implementation', 'Code generation',                    2, ARRAY['coder'],               FALSE, 'test',      'plan',     FALSE),
    ((SELECT id FROM w), 'test',      'Testing',        'Test creation and execution',        3, ARRAY['tester'],              FALSE, 'review',    'implement',FALSE),
    ((SELECT id FROM w), 'review',    'Review',         'Code and security review',           4, ARRAY['reviewer', 'security'],TRUE,  'document',  'implement',FALSE),
    ((SELECT id FROM w), 'document',  'Documentation',  'Documentation generation',           5, ARRAY['doc-writer'],          FALSE, 'deploy',    'review',   FALSE),
    ((SELECT id FROM w), 'deploy',    'Deployment',     'Build and deploy',                   6, ARRAY['deployer'],            FALSE, 'complete',  'review',   FALSE),
    ((SELECT id FROM w), 'complete',  'Complete',        'Pipeline complete',                  7, ARRAY[]::TEXT[],              FALSE, '',          '',         TRUE);

-- Governance
WITH p AS (SELECT id FROM profiles WHERE name = 'software-dev')
INSERT INTO governance_configs (profile_id, auto_approve_threshold, review_threshold, abort_threshold)
VALUES ((SELECT id FROM p), 0.850, 0.600, 0.300);

-- Governance policies
WITH p AS (SELECT id FROM profiles WHERE name = 'software-dev')
INSERT INTO governance_policies (profile_id, policy_id, name, description, action, conditions, priority, tags)
VALUES
    ((SELECT id FROM p), 'require-tests', 'Require test coverage',
     'Code changes must have associated tests',
     'review', ARRAY['test_coverage < 0.8'], 10, ARRAY['quality']),

    ((SELECT id FROM p), 'block-secrets', 'Block committed secrets',
     'Prevent code containing API keys or secrets from proceeding',
     'deny', ARRAY['has_secrets == True'], 20, ARRAY['security']);

-- Work item type
WITH p AS (SELECT id FROM profiles WHERE name = 'software-dev')
INSERT INTO work_item_types (profile_id, type_id, name, description)
VALUES ((SELECT id FROM p), 'dev-task', 'Development Task', 'A software development task');

WITH wit AS (
    SELECT wit.id FROM work_item_types wit
    JOIN profiles p ON wit.profile_id = p.id
    WHERE p.name = 'software-dev' AND wit.type_id = 'dev-task'
)
INSERT INTO work_item_type_fields (work_item_type_id, name, field_type, required, enum_values)
VALUES
    ((SELECT id FROM wit), 'task_description', 'text',   TRUE,  NULL),
    ((SELECT id FROM wit), 'repository_url',   'string', FALSE, NULL),
    ((SELECT id FROM wit), 'branch',           'string', FALSE, NULL),
    ((SELECT id FROM wit), 'task_type',        'enum',   FALSE, ARRAY['feature', 'bugfix', 'refactor', 'docs', 'test']);

COMMIT;
