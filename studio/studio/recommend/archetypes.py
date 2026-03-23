"""Catalog of reusable agent archetypes with keyword triggers and default configs.

Two catalog tiers:
1. **Domain archetypes** — domain-specific agents (trading, healthcare, legal, etc.)
   matched first when the description indicates a specific domain.
2. **Software development archetypes** — generic dev/ops roles matched when the
   description is about building software.

Each archetype defines a template agent with sensible defaults that can be
recommended based on keyword matching (greenfield) or structural analysis
(existing codebase).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Archetype:
    """A reusable agent archetype template."""

    id: str
    name: str
    description: str
    system_prompt: str
    keywords: list[str]
    default_phase: str
    category: str  # management | development | review | ops | domain
    skills: list[str] = field(default_factory=list)
    domain: str = ""  # empty = software-dev, otherwise domain name


@dataclass(frozen=True)
class DomainCatalog:
    """A collection of archetypes for a specific domain."""

    domain: str
    trigger_keywords: list[str]
    archetypes: list[Archetype]
    phase_order: list[str]


# ---------------------------------------------------------------------------
# Software development archetypes (original set)
# ---------------------------------------------------------------------------

SOFTWARE_DEV_ARCHETYPES: list[Archetype] = [
    Archetype(
        id="pm-agent",
        name="PM / Requirements Agent",
        description="Gathers and refines product requirements, writes user stories, and prioritizes features.",
        system_prompt="You are a product manager. Analyze requirements, write user stories, and prioritize features based on business value and technical feasibility.",
        keywords=["product", "requirements", "user stories", "features", "pm", "product manager", "backlog", "roadmap"],
        default_phase="requirements",
        category="management",
        skills=["requirements-gathering", "user-story-writing"],
    ),
    Archetype(
        id="architect-agent",
        name="Architect Agent",
        description="Designs system architecture, defines APIs, and makes technology decisions.",
        system_prompt="You are a software architect. Design system architecture, define API contracts, choose appropriate technologies, and document architectural decisions.",
        keywords=["architecture", "design", "system design", "api design", "architect", "microservices", "monolith", "scalability"],
        default_phase="design",
        category="management",
        skills=["system-design", "api-design"],
    ),
    Archetype(
        id="backend-dev-agent",
        name="Backend Developer Agent",
        description="Implements server-side logic, APIs, database schemas, and business rules.",
        system_prompt="You are a backend developer. Implement server-side logic, REST/GraphQL APIs, database schemas, and business rules following best practices.",
        keywords=["api", "backend", "server", "database", "python", "node", "rest", "graphql", "fastapi", "express", "django", "flask", "sql", "postgresql", "mysql", "mongodb"],
        default_phase="implementation",
        category="development",
        skills=["backend-development", "api-implementation", "database-design"],
    ),
    Archetype(
        id="frontend-dev-agent",
        name="Frontend Developer Agent",
        description="Builds user interfaces, implements components, and handles client-side state.",
        system_prompt="You are a frontend developer. Build responsive user interfaces, implement reusable components, manage client-side state, and ensure accessibility.",
        keywords=["frontend", "ui", "react", "angular", "vue", "web app", "mobile", "css", "tailwind", "nextjs", "typescript", "javascript", "svelte"],
        default_phase="implementation",
        category="development",
        skills=["frontend-development", "ui-implementation"],
    ),
    Archetype(
        id="code-reviewer-agent",
        name="Code Reviewer Agent",
        description="Reviews code for quality, consistency, best practices, and potential issues.",
        system_prompt="You are a code reviewer. Review code changes for quality, consistency, adherence to best practices, potential bugs, and maintainability.",
        keywords=["code review", "review", "quality", "best practices", "lint", "standards"],
        default_phase="review",
        category="review",
        skills=["code-review", "quality-assurance"],
    ),
    Archetype(
        id="security-scanner-agent",
        name="Security Scanner Agent",
        description="Audits code and infrastructure for security vulnerabilities and compliance issues.",
        system_prompt="You are a security auditor. Scan code for vulnerabilities (OWASP Top 10), review authentication/authorization patterns, and verify security best practices.",
        keywords=["security", "audit", "vulnerability", "owasp", "penetration", "compliance", "authentication", "authorization"],
        default_phase="security",
        category="review",
        skills=["security-scanning", "vulnerability-assessment"],
    ),
    Archetype(
        id="tester-agent",
        name="Tester Agent",
        description="Writes and maintains test suites, identifies test gaps, and validates functionality.",
        system_prompt="You are a QA engineer. Write unit tests, integration tests, and end-to-end tests. Identify test coverage gaps and validate that implementations meet requirements.",
        keywords=["test", "qa", "quality assurance", "pytest", "jest", "testing", "unit test", "integration test", "e2e", "cypress", "playwright"],
        default_phase="testing",
        category="review",
        skills=["test-writing", "test-automation"],
    ),
    Archetype(
        id="devops-agent",
        name="DevOps Agent",
        description="Manages deployment pipelines, infrastructure-as-code, and containerization.",
        system_prompt="You are a DevOps engineer. Configure CI/CD pipelines, manage infrastructure as code, set up containerization, and ensure reliable deployments.",
        keywords=["deploy", "ci/cd", "infrastructure", "docker", "terraform", "kubernetes", "aws", "azure", "gcp", "pipeline", "github actions", "jenkins", "devops"],
        default_phase="deployment",
        category="ops",
        skills=["ci-cd", "infrastructure-management", "containerization"],
    ),
    Archetype(
        id="data-analyst-agent",
        name="Data Analyst Agent",
        description="Analyzes data, builds dashboards, and implements ETL pipelines.",
        system_prompt="You are a data analyst. Analyze datasets, create visualizations, build dashboards, and implement ETL pipelines for data processing.",
        keywords=["data", "analytics", "reporting", "dashboard", "etl", "data pipeline", "visualization", "pandas", "spark", "sql"],
        default_phase="analysis",
        category="development",
        skills=["data-analysis", "etl-pipeline"],
    ),
    Archetype(
        id="content-moderator-agent",
        name="Content Moderator Agent",
        description="Moderates user-generated content against safety policies and community guidelines.",
        system_prompt="You are a content moderator. Review user-generated content against safety policies, flag violations, and ensure compliance with community guidelines.",
        keywords=["moderation", "content", "filter", "safety", "policy", "content moderation", "trust and safety"],
        default_phase="moderation",
        category="development",
        skills=["content-moderation", "policy-enforcement"],
    ),
    Archetype(
        id="researcher-agent",
        name="Researcher Agent",
        description="Researches topics, synthesizes information from multiple sources, and provides summaries.",
        system_prompt="You are a researcher. Research topics thoroughly, gather information from multiple sources, synthesize findings, and provide actionable summaries.",
        keywords=["research", "search", "analysis", "source", "synthesis", "investigate", "literature review"],
        default_phase="research",
        category="development",
        skills=["research", "information-synthesis"],
    ),
    Archetype(
        id="technical-writer-agent",
        name="Technical Writer Agent",
        description="Creates and maintains technical documentation, API docs, and user guides.",
        system_prompt="You are a technical writer. Create clear, comprehensive documentation including API references, user guides, architecture docs, and runbooks.",
        keywords=["documentation", "docs", "technical writing", "api docs", "readme", "wiki", "user guide", "runbook"],
        default_phase="documentation",
        category="ops",
        skills=["technical-writing", "documentation"],
    ),
]

SOFTWARE_DEV_PHASE_ORDER: list[str] = [
    "research",
    "requirements",
    "design",
    "analysis",
    "implementation",
    "moderation",
    "review",
    "security",
    "testing",
    "documentation",
    "deployment",
]

# ---------------------------------------------------------------------------
# Domain catalogs
# ---------------------------------------------------------------------------

DOMAIN_CATALOGS: list[DomainCatalog] = [
    # ---- Trading / Finance ----
    DomainCatalog(
        domain="trading",
        trigger_keywords=[
            "trading", "trade", "stock", "stocks", "forex", "crypto", "cryptocurrency",
            "portfolio", "hedge fund", "investment", "equities", "options", "futures",
            "algo trading", "algorithmic trading", "quant", "quantitative",
            "market making", "arbitrage", "derivatives", "fixed income", "commodities",
        ],
        phase_order=[
            "market-research",
            "strategy-development",
            "risk-assessment",
            "signal-generation",
            "execution",
            "monitoring",
            "compliance-review",
            "reporting",
        ],
        archetypes=[
            Archetype(
                id="market-analyst-agent",
                name="Market Research Analyst",
                description="Analyzes market conditions, trends, economic indicators, and news to identify opportunities.",
                system_prompt="You are a market research analyst. Analyze market data, economic indicators, news sentiment, and technical patterns to identify trading opportunities and assess market conditions.",
                keywords=["market", "analysis", "trends", "indicators", "economic", "sentiment", "technical analysis", "fundamental analysis"],
                default_phase="market-research",
                category="domain",
                skills=["market-analysis", "trend-identification", "sentiment-analysis"],
                domain="trading",
            ),
            Archetype(
                id="strategy-agent",
                name="Trading Strategy Agent",
                description="Develops, backtests, and optimizes trading strategies based on market analysis.",
                system_prompt="You are a quantitative trading strategist. Design trading strategies, define entry/exit rules, optimize parameters, and backtest against historical data to maximize risk-adjusted returns.",
                keywords=["strategy", "backtest", "algorithm", "signal", "entry", "exit", "optimization", "alpha"],
                default_phase="strategy-development",
                category="domain",
                skills=["strategy-design", "backtesting", "parameter-optimization"],
                domain="trading",
            ),
            Archetype(
                id="risk-manager-agent",
                name="Risk Manager Agent",
                description="Assesses and manages portfolio risk, position sizing, and exposure limits.",
                system_prompt="You are a risk manager. Evaluate portfolio risk metrics (VaR, drawdown, Sharpe ratio), enforce position limits, monitor exposure, and recommend hedging strategies to protect capital.",
                keywords=["risk", "var", "drawdown", "exposure", "position sizing", "hedge", "volatility", "correlation"],
                default_phase="risk-assessment",
                category="domain",
                skills=["risk-assessment", "position-sizing", "exposure-management"],
                domain="trading",
            ),
            Archetype(
                id="signal-generator-agent",
                name="Signal Generator Agent",
                description="Generates buy/sell signals from strategy rules, indicators, and market data.",
                system_prompt="You are a signal generation engine. Process real-time and historical market data through strategy rules and technical indicators to generate actionable buy/sell/hold signals with confidence levels.",
                keywords=["signal", "indicator", "buy", "sell", "trigger", "momentum", "crossover", "breakout"],
                default_phase="signal-generation",
                category="domain",
                skills=["signal-generation", "indicator-computation"],
                domain="trading",
            ),
            Archetype(
                id="trade-executor-agent",
                name="Trade Execution Agent",
                description="Executes trades with optimal timing, order types, and slippage management.",
                system_prompt="You are a trade execution specialist. Execute orders with optimal timing, select appropriate order types (limit, market, stop), minimize slippage and market impact, and manage partial fills.",
                keywords=["execution", "order", "fill", "slippage", "market impact", "limit order", "stop loss", "take profit"],
                default_phase="execution",
                category="domain",
                skills=["order-execution", "slippage-management"],
                domain="trading",
            ),
            Archetype(
                id="portfolio-monitor-agent",
                name="Portfolio Monitor Agent",
                description="Monitors live positions, P&L, and market conditions for anomalies and alerts.",
                system_prompt="You are a portfolio monitoring agent. Track live positions, unrealized P&L, margin usage, and market conditions in real-time. Detect anomalies, trigger alerts on threshold breaches, and recommend position adjustments.",
                keywords=["monitor", "portfolio", "p&l", "pnl", "position", "alert", "threshold", "real-time"],
                default_phase="monitoring",
                category="domain",
                skills=["portfolio-monitoring", "anomaly-detection", "alerting"],
                domain="trading",
            ),
            Archetype(
                id="compliance-agent",
                name="Compliance & Regulatory Agent",
                description="Ensures trading activity complies with regulations, limits, and internal policies.",
                system_prompt="You are a compliance officer. Review trading activity against regulatory requirements (SEC, FINRA, MiFID), enforce concentration limits, monitor for wash trading or market manipulation, and generate compliance reports.",
                keywords=["compliance", "regulation", "regulatory", "sec", "finra", "mifid", "audit", "reporting"],
                default_phase="compliance-review",
                category="domain",
                skills=["regulatory-compliance", "trade-surveillance"],
                domain="trading",
            ),
            Archetype(
                id="performance-reporter-agent",
                name="Performance Reporting Agent",
                description="Generates performance reports, attribution analysis, and portfolio summaries.",
                system_prompt="You are a performance analyst. Generate daily/weekly/monthly performance reports including returns attribution, benchmark comparison, risk metrics, and trade log summaries for stakeholders.",
                keywords=["report", "performance", "attribution", "benchmark", "returns", "summary"],
                default_phase="reporting",
                category="domain",
                skills=["performance-reporting", "attribution-analysis"],
                domain="trading",
            ),
        ],
    ),

    # ---- Healthcare ----
    DomainCatalog(
        domain="healthcare",
        trigger_keywords=[
            "healthcare", "health", "medical", "clinical", "patient", "hospital",
            "diagnosis", "treatment", "ehr", "hl7", "fhir", "pharmacy", "nursing",
            "telemedicine", "telehealth", "lab results", "radiology", "pathology",
        ],
        phase_order=[
            "intake-triage",
            "clinical-analysis",
            "diagnosis-support",
            "treatment-planning",
            "quality-review",
            "compliance-check",
            "documentation",
            "follow-up",
        ],
        archetypes=[
            Archetype(
                id="triage-agent",
                name="Intake & Triage Agent",
                description="Processes patient intake data, prioritizes by urgency, and routes to appropriate care paths.",
                system_prompt="You are a medical triage specialist. Analyze patient symptoms, medical history, and vitals to assess urgency, assign priority levels, and route to the appropriate clinical pathway.",
                keywords=["triage", "intake", "urgency", "priority", "symptoms", "vitals"],
                default_phase="intake-triage",
                category="domain",
                skills=["patient-triage", "urgency-assessment"],
                domain="healthcare",
            ),
            Archetype(
                id="clinical-analyst-agent",
                name="Clinical Data Analyst",
                description="Analyzes clinical data, lab results, imaging reports, and patient history.",
                system_prompt="You are a clinical data analyst. Review lab results, imaging reports, patient history, and clinical notes to identify patterns, flag abnormalities, and provide data-driven clinical insights.",
                keywords=["clinical", "lab", "imaging", "patient history", "analysis", "ehr"],
                default_phase="clinical-analysis",
                category="domain",
                skills=["clinical-analysis", "lab-interpretation"],
                domain="healthcare",
            ),
            Archetype(
                id="diagnosis-support-agent",
                name="Diagnosis Support Agent",
                description="Provides differential diagnosis suggestions based on clinical evidence.",
                system_prompt="You are a clinical decision support agent. Based on symptoms, test results, and patient history, generate ranked differential diagnoses with supporting evidence and recommended confirmatory tests.",
                keywords=["diagnosis", "differential", "clinical decision", "symptoms"],
                default_phase="diagnosis-support",
                category="domain",
                skills=["differential-diagnosis", "clinical-reasoning"],
                domain="healthcare",
            ),
            Archetype(
                id="treatment-planner-agent",
                name="Treatment Planning Agent",
                description="Recommends evidence-based treatment plans, medications, and care protocols.",
                system_prompt="You are a treatment planning specialist. Recommend evidence-based treatment options, medication regimens, therapy plans, and care protocols while considering patient-specific factors, contraindications, and guidelines.",
                keywords=["treatment", "medication", "therapy", "protocol", "care plan"],
                default_phase="treatment-planning",
                category="domain",
                skills=["treatment-planning", "medication-review"],
                domain="healthcare",
            ),
            Archetype(
                id="medical-qa-agent",
                name="Medical Quality Assurance Agent",
                description="Reviews clinical decisions for quality, safety, and adherence to guidelines.",
                system_prompt="You are a medical quality reviewer. Evaluate clinical decisions against evidence-based guidelines, check for medication interactions, verify appropriate testing, and flag potential safety concerns.",
                keywords=["quality", "safety", "guidelines", "review", "interaction"],
                default_phase="quality-review",
                category="domain",
                skills=["clinical-quality-review", "safety-check"],
                domain="healthcare",
            ),
            Archetype(
                id="hipaa-compliance-agent",
                name="HIPAA Compliance Agent",
                description="Ensures healthcare data handling meets HIPAA and regulatory requirements.",
                system_prompt="You are a healthcare compliance specialist. Verify that all data handling, documentation, and communication meets HIPAA, HITECH, and relevant regulatory requirements. Flag PHI exposure risks and recommend remediations.",
                keywords=["hipaa", "compliance", "phi", "privacy", "regulation"],
                default_phase="compliance-check",
                category="domain",
                skills=["hipaa-compliance", "privacy-audit"],
                domain="healthcare",
            ),
            Archetype(
                id="clinical-documentation-agent",
                name="Clinical Documentation Agent",
                description="Generates and maintains clinical notes, discharge summaries, and care documentation.",
                system_prompt="You are a clinical documentation specialist. Generate structured clinical notes, discharge summaries, referral letters, and care coordination documentation following standard medical formats.",
                keywords=["documentation", "notes", "discharge", "summary", "records"],
                default_phase="documentation",
                category="domain",
                skills=["clinical-documentation", "medical-writing"],
                domain="healthcare",
            ),
            Archetype(
                id="follow-up-agent",
                name="Follow-up & Monitoring Agent",
                description="Tracks patient outcomes, schedules follow-ups, and monitors treatment adherence.",
                system_prompt="You are a patient follow-up coordinator. Track treatment outcomes, schedule follow-up appointments, monitor medication adherence, and escalate deteriorating conditions.",
                keywords=["follow-up", "monitoring", "outcomes", "adherence", "scheduling"],
                default_phase="follow-up",
                category="domain",
                skills=["patient-monitoring", "follow-up-coordination"],
                domain="healthcare",
            ),
        ],
    ),

    # ---- Legal ----
    DomainCatalog(
        domain="legal",
        trigger_keywords=[
            "legal", "law", "attorney", "lawyer", "contract", "litigation",
            "compliance", "regulatory", "patent", "trademark", "intellectual property",
            "corporate law", "legal review", "due diligence", "dispute",
        ],
        phase_order=[
            "case-intake",
            "legal-research",
            "document-analysis",
            "risk-assessment",
            "drafting",
            "review",
            "compliance-check",
            "reporting",
        ],
        archetypes=[
            Archetype(
                id="case-intake-agent",
                name="Case Intake Agent",
                description="Processes new legal matters, extracts key facts, and classifies case type.",
                system_prompt="You are a legal intake specialist. Review incoming legal matters, extract key facts, identify relevant parties, classify the case type, assess urgency, and route to the appropriate practice area.",
                keywords=["intake", "case", "matter", "facts", "classify"],
                default_phase="case-intake",
                category="domain",
                skills=["case-intake", "fact-extraction"],
                domain="legal",
            ),
            Archetype(
                id="legal-researcher-agent",
                name="Legal Research Agent",
                description="Researches case law, statutes, regulations, and legal precedents.",
                system_prompt="You are a legal researcher. Research relevant case law, statutes, regulations, and legal precedents. Identify applicable legal theories, jurisdictional considerations, and analogous cases.",
                keywords=["research", "case law", "statute", "precedent", "jurisdiction"],
                default_phase="legal-research",
                category="domain",
                skills=["legal-research", "case-law-analysis"],
                domain="legal",
            ),
            Archetype(
                id="contract-analyst-agent",
                name="Contract & Document Analyst",
                description="Analyzes contracts, identifies risks, obligations, and key terms.",
                system_prompt="You are a contract analyst. Review contracts and legal documents to identify key terms, obligations, liabilities, termination clauses, indemnification provisions, and potential risks or ambiguities.",
                keywords=["contract", "document", "clause", "terms", "obligations", "liability"],
                default_phase="document-analysis",
                category="domain",
                skills=["contract-analysis", "document-review"],
                domain="legal",
            ),
            Archetype(
                id="legal-risk-agent",
                name="Legal Risk Assessment Agent",
                description="Evaluates legal exposure, litigation risk, and regulatory risk.",
                system_prompt="You are a legal risk analyst. Assess legal exposure, litigation probability, regulatory risk, and potential damages. Provide risk ratings and recommend mitigation strategies.",
                keywords=["risk", "exposure", "litigation", "damages", "mitigation"],
                default_phase="risk-assessment",
                category="domain",
                skills=["legal-risk-assessment", "exposure-analysis"],
                domain="legal",
            ),
            Archetype(
                id="legal-drafter-agent",
                name="Legal Drafting Agent",
                description="Drafts legal documents, contracts, briefs, and correspondence.",
                system_prompt="You are a legal drafting specialist. Draft contracts, legal briefs, memoranda, corporate resolutions, and legal correspondence with precise language, proper legal citations, and appropriate protective clauses.",
                keywords=["draft", "brief", "memorandum", "correspondence", "writing"],
                default_phase="drafting",
                category="domain",
                skills=["legal-drafting", "brief-writing"],
                domain="legal",
            ),
            Archetype(
                id="legal-reviewer-agent",
                name="Legal Review Agent",
                description="Reviews legal work product for accuracy, completeness, and consistency.",
                system_prompt="You are a senior legal reviewer. Review legal documents, research memos, and drafts for accuracy, completeness, logical consistency, proper citations, and adherence to applicable standards.",
                keywords=["review", "accuracy", "completeness", "quality"],
                default_phase="review",
                category="domain",
                skills=["legal-review", "quality-control"],
                domain="legal",
            ),
            Archetype(
                id="regulatory-compliance-agent",
                name="Regulatory Compliance Agent",
                description="Ensures compliance with applicable laws, regulations, and industry standards.",
                system_prompt="You are a regulatory compliance specialist. Verify compliance with applicable laws, regulations, and industry standards. Identify gaps, recommend corrective actions, and track regulatory changes.",
                keywords=["compliance", "regulatory", "standards", "audit"],
                default_phase="compliance-check",
                category="domain",
                skills=["regulatory-compliance", "compliance-monitoring"],
                domain="legal",
            ),
        ],
    ),

    # ---- Marketing ----
    DomainCatalog(
        domain="marketing",
        trigger_keywords=[
            "marketing", "campaign", "brand", "advertising", "ad", "social media",
            "seo", "sem", "content marketing", "email marketing", "growth",
            "conversion", "funnel", "lead generation", "digital marketing",
        ],
        phase_order=[
            "market-research",
            "strategy",
            "content-creation",
            "campaign-setup",
            "execution",
            "monitoring",
            "analysis",
            "reporting",
        ],
        archetypes=[
            Archetype(
                id="market-research-agent",
                name="Market Research Agent",
                description="Researches target audiences, competitors, and market trends.",
                system_prompt="You are a market researcher. Analyze target demographics, competitor positioning, market trends, and customer segments to inform marketing strategy and campaign targeting.",
                keywords=["market research", "audience", "competitor", "demographics", "segments"],
                default_phase="market-research",
                category="domain",
                skills=["market-research", "competitive-analysis"],
                domain="marketing",
            ),
            Archetype(
                id="campaign-strategist-agent",
                name="Campaign Strategist Agent",
                description="Designs marketing strategies, campaign plans, and channel mix.",
                system_prompt="You are a marketing strategist. Design campaign strategies including objectives, target audiences, channel mix, messaging framework, budget allocation, and KPIs.",
                keywords=["strategy", "campaign", "channel", "messaging", "budget", "kpi"],
                default_phase="strategy",
                category="domain",
                skills=["campaign-strategy", "channel-planning"],
                domain="marketing",
            ),
            Archetype(
                id="content-creator-agent",
                name="Content Creator Agent",
                description="Creates marketing copy, social posts, email campaigns, and ad creatives.",
                system_prompt="You are a content creator. Write compelling marketing copy, social media posts, email campaigns, blog articles, and ad creatives that align with brand voice and drive engagement.",
                keywords=["content", "copy", "social media", "email", "creative", "blog"],
                default_phase="content-creation",
                category="domain",
                skills=["copywriting", "content-creation"],
                domain="marketing",
            ),
            Archetype(
                id="seo-agent",
                name="SEO & Analytics Agent",
                description="Optimizes content for search, tracks performance metrics, and analyzes campaigns.",
                system_prompt="You are an SEO and analytics specialist. Optimize content for search engines, analyze campaign performance metrics, track conversion funnels, and provide data-driven recommendations for improvement.",
                keywords=["seo", "analytics", "conversion", "funnel", "metrics", "performance"],
                default_phase="analysis",
                category="domain",
                skills=["seo-optimization", "analytics"],
                domain="marketing",
            ),
            Archetype(
                id="brand-manager-agent",
                name="Brand Manager Agent",
                description="Ensures brand consistency, manages brand guidelines, and protects brand reputation.",
                system_prompt="You are a brand manager. Ensure all marketing materials align with brand guidelines, maintain consistent voice and visual identity, monitor brand reputation, and manage brand positioning.",
                keywords=["brand", "guidelines", "identity", "reputation", "positioning"],
                default_phase="monitoring",
                category="domain",
                skills=["brand-management", "reputation-monitoring"],
                domain="marketing",
            ),
        ],
    ),

    # ---- E-Commerce / Retail ----
    DomainCatalog(
        domain="ecommerce",
        trigger_keywords=[
            "ecommerce", "e-commerce", "retail", "shop", "store", "cart",
            "checkout", "inventory", "catalog", "product listing", "marketplace",
            "order management", "fulfillment", "shipping", "returns",
        ],
        phase_order=[
            "catalog-management",
            "pricing-optimization",
            "order-processing",
            "inventory-management",
            "fulfillment",
            "customer-support",
            "analytics",
            "reporting",
        ],
        archetypes=[
            Archetype(
                id="catalog-agent",
                name="Product Catalog Agent",
                description="Manages product listings, descriptions, categorization, and attributes.",
                system_prompt="You are a product catalog manager. Manage product listings, write compelling descriptions, ensure accurate categorization, optimize product attributes for searchability, and maintain data quality.",
                keywords=["catalog", "product", "listing", "description", "category", "attributes"],
                default_phase="catalog-management",
                category="domain",
                skills=["catalog-management", "product-optimization"],
                domain="ecommerce",
            ),
            Archetype(
                id="pricing-agent",
                name="Pricing & Promotions Agent",
                description="Optimizes pricing strategies, manages discounts, and runs promotions.",
                system_prompt="You are a pricing strategist. Analyze competitor pricing, demand elasticity, and margins to optimize pricing. Design promotional campaigns, manage discount rules, and maximize revenue per customer.",
                keywords=["pricing", "promotion", "discount", "margin", "revenue"],
                default_phase="pricing-optimization",
                category="domain",
                skills=["pricing-optimization", "promotional-planning"],
                domain="ecommerce",
            ),
            Archetype(
                id="order-agent",
                name="Order Processing Agent",
                description="Manages order lifecycle from placement through fulfillment.",
                system_prompt="You are an order processing specialist. Manage the full order lifecycle including validation, payment verification, fraud screening, allocation, and status communication to customers.",
                keywords=["order", "checkout", "payment", "fulfillment", "processing"],
                default_phase="order-processing",
                category="domain",
                skills=["order-management", "payment-processing"],
                domain="ecommerce",
            ),
            Archetype(
                id="inventory-agent",
                name="Inventory Management Agent",
                description="Tracks inventory levels, forecasts demand, and manages replenishment.",
                system_prompt="You are an inventory manager. Track stock levels across locations, forecast demand, trigger replenishment orders, manage safety stock, and optimize warehouse allocation to prevent stockouts and overstock.",
                keywords=["inventory", "stock", "warehouse", "replenishment", "demand forecast"],
                default_phase="inventory-management",
                category="domain",
                skills=["inventory-management", "demand-forecasting"],
                domain="ecommerce",
            ),
            Archetype(
                id="customer-support-agent",
                name="Customer Support Agent",
                description="Handles customer inquiries, complaints, returns, and satisfaction tracking.",
                system_prompt="You are a customer support specialist. Handle customer inquiries, process returns and refunds, resolve complaints, track customer satisfaction, and escalate complex issues appropriately.",
                keywords=["customer", "support", "returns", "complaints", "satisfaction"],
                default_phase="customer-support",
                category="domain",
                skills=["customer-support", "issue-resolution"],
                domain="ecommerce",
            ),
        ],
    ),

    # ---- Education ----
    DomainCatalog(
        domain="education",
        trigger_keywords=[
            "education", "learning", "teaching", "course", "curriculum",
            "student", "teacher", "lms", "e-learning", "training",
            "assessment", "tutoring", "academic", "school", "university",
        ],
        phase_order=[
            "needs-assessment",
            "curriculum-design",
            "content-development",
            "delivery",
            "assessment",
            "feedback",
            "improvement",
        ],
        archetypes=[
            Archetype(
                id="curriculum-designer-agent",
                name="Curriculum Designer Agent",
                description="Designs learning paths, course structures, and educational content frameworks.",
                system_prompt="You are a curriculum designer. Design structured learning paths, define learning objectives, organize course modules, map prerequisites, and ensure alignment with educational standards and outcomes.",
                keywords=["curriculum", "course", "learning path", "objectives", "modules"],
                default_phase="curriculum-design",
                category="domain",
                skills=["curriculum-design", "learning-path-creation"],
                domain="education",
            ),
            Archetype(
                id="content-developer-agent",
                name="Educational Content Developer",
                description="Creates lessons, exercises, quizzes, and learning materials.",
                system_prompt="You are an educational content developer. Create engaging lessons, interactive exercises, assessment questions, study guides, and multimedia learning materials tailored to the target audience and learning objectives.",
                keywords=["content", "lesson", "exercise", "quiz", "materials"],
                default_phase="content-development",
                category="domain",
                skills=["content-development", "assessment-creation"],
                domain="education",
            ),
            Archetype(
                id="tutor-agent",
                name="Tutoring Agent",
                description="Provides personalized instruction, answers questions, and adapts to learner pace.",
                system_prompt="You are a personal tutor. Provide clear explanations, answer student questions, adapt your teaching approach to the learner's level and pace, offer practice problems, and give encouraging feedback.",
                keywords=["tutor", "teaching", "instruction", "student", "personalized"],
                default_phase="delivery",
                category="domain",
                skills=["tutoring", "adaptive-teaching"],
                domain="education",
            ),
            Archetype(
                id="assessment-agent",
                name="Assessment & Grading Agent",
                description="Evaluates student work, provides rubric-based grading, and identifies learning gaps.",
                system_prompt="You are an assessment specialist. Evaluate student submissions against rubrics, provide detailed feedback, identify knowledge gaps, track learning progress, and recommend targeted remediation.",
                keywords=["assessment", "grading", "rubric", "evaluation", "progress"],
                default_phase="assessment",
                category="domain",
                skills=["assessment", "rubric-grading"],
                domain="education",
            ),
            Archetype(
                id="learning-analytics-agent",
                name="Learning Analytics Agent",
                description="Tracks learner engagement, identifies at-risk students, and optimizes content effectiveness.",
                system_prompt="You are a learning analytics specialist. Analyze engagement metrics, completion rates, assessment scores, and time-on-task to identify at-risk learners, measure content effectiveness, and recommend improvements.",
                keywords=["analytics", "engagement", "at-risk", "effectiveness", "metrics"],
                default_phase="improvement",
                category="domain",
                skills=["learning-analytics", "engagement-tracking"],
                domain="education",
            ),
        ],
    ),
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_domain(tokens: set[str], full_text: str) -> DomainCatalog | None:
    """Detect which domain catalog best matches the input.

    Returns the best-matching domain catalog, or None if the input
    looks like a software development project.
    """
    best_catalog: DomainCatalog | None = None
    best_score = 0

    for catalog in DOMAIN_CATALOGS:
        score = 0
        for kw in catalog.trigger_keywords:
            kw_lower = kw.lower()
            if " " in kw_lower:
                if kw_lower in full_text:
                    score += 2
            elif kw_lower in tokens:
                score += 2
            else:
                for token in tokens:
                    # Only allow partial matches for tokens >= 4 chars
                    # to avoid false positives from short words like "a", "to"
                    if len(token) >= 4 and (kw_lower in token or token in kw_lower):
                        score += 1
                        break
        if score > best_score:
            best_score = score
            best_catalog = catalog

    # Only return a domain if there's meaningful signal (at least 2 points)
    if best_score >= 2:
        return best_catalog
    return None


def get_archetypes_for_domain(domain: str | None) -> list[Archetype]:
    """Return archetypes for a domain, falling back to software dev."""
    if domain:
        for catalog in DOMAIN_CATALOGS:
            if catalog.domain == domain:
                return catalog.archetypes
    return SOFTWARE_DEV_ARCHETYPES


def get_phase_order_for_domain(domain: str | None) -> list[str]:
    """Return phase ordering for a domain."""
    if domain:
        for catalog in DOMAIN_CATALOGS:
            if catalog.domain == domain:
                return catalog.phase_order
    return SOFTWARE_DEV_PHASE_ORDER


def get_archetype(archetype_id: str) -> Archetype | None:
    """Look up an archetype by its ID across all catalogs."""
    for arch in SOFTWARE_DEV_ARCHETYPES:
        if arch.id == archetype_id:
            return arch
    for catalog in DOMAIN_CATALOGS:
        for arch in catalog.archetypes:
            if arch.id == archetype_id:
                return arch
    return None


def get_phase_order(phase_id: str, domain: str | None = None) -> int:
    """Return the canonical ordering for a phase name."""
    order = get_phase_order_for_domain(domain)
    try:
        return order.index(phase_id)
    except ValueError:
        return len(order)
