# PropFlow AI

## Autonomous Real Estate Lead Management & Sales Automation Platform

> **Project type:** Agentic AI · Workflow Automation · CRM Integration ·
> Business Process Automation\
> **Primary objective:** Automate the journey from initial real-estate
> inquiry to qualified CRM lead, timely sales follow-up, and management
> reporting.

------------------------------------------------------------------------

## 1. Project Overview

PropFlow AI is an AI-powered workflow automation platform designed for
real-estate agencies and property marketplaces. It connects lead
acquisition channels, AI-assisted qualification, property matching, Odoo
CRM, customer messaging, and operational reporting into a coordinated
workflow.

When a prospective buyer submits an inquiry through a website form or
supported messaging channel, the platform validates and structures the
information, identifies the buyer's requirements, calculates a
transparent lead-priority score, searches for relevant properties,
creates or updates the CRM record, assigns ownership, and initiates an
appropriate follow-up. High-priority or ambiguous cases can be escalated
to a human sales representative.

The system uses **n8n as the business workflow orchestrator**, **Odoo as
the CRM and sales system of record**, and a separately deployable
**Python/FastAPI service with LangGraph** for more complex AI reasoning
and agent workflows.

PropFlow AI is intended to demonstrate practical business
automation---not simply a conversational chatbot. Its emphasis is on
reliable integrations, traceable decisions, human oversight, error
recovery, and measurable operational performance.

## 2. Problem Statement

Real-estate sales teams may receive inquiries through multiple channels
and manually perform repetitive tasks:

-   Copying customer details into a CRM.
-   Understanding free-text requirements and identifying missing
    information.
-   Determining lead urgency and assigning a sales representative.
-   Searching listings that match a buyer's budget and preferences.
-   Sending initial replies and reminders.
-   Updating CRM stages and interaction history.
-   Preparing periodic reports for management.

Manual handling can create delayed responses, inconsistent records,
missed follow-ups, duplicate leads, and limited visibility into the
sales pipeline.

PropFlow AI addresses these challenges by coordinating the process
through event-driven automation, structured AI extraction, explicit
business rules, CRM integration, and controlled customer communication.

## 3. Goals

### Primary goals

1.  Capture and normalize inquiries from configured channels.
2.  Extract useful buyer requirements from natural-language messages.
3.  Score and route leads using explainable business rules.
4.  Create, update, and deduplicate lead records in Odoo.
5.  Match buyer requirements against an available property catalog.
6.  Initiate approved email or WhatsApp communication.
7.  Escalate high-priority, uncertain, or exceptional cases to humans.
8.  Maintain interaction history and CRM state.
9.  Produce operational reports and workflow health indicators.
10. Make failures visible and recoverable through validation, retries,
    logs, and alerts.

### Non-goals for the initial version

-   Replacing sales representatives or making final sales decisions.
-   Guaranteeing property availability or pricing without a current
    source of truth.
-   Sending unrestricted autonomous messages.
-   Predicting customer willingness to buy as a definitive fact.
-   Processing real customer data before access controls, privacy, and
    consent requirements are addressed.

## 4. Target Users

  -----------------------------------------------------------------------
  User                                Primary needs
  ----------------------------------- -----------------------------------
  Sales representative                Receive assigned, contextualized
                                      leads and manage follow-ups

  Sales manager                       Monitor pipeline, response times,
                                      workload, and escalations

  Operations administrator            Configure workflow rules,
                                      integrations, and exception
                                      handling

  System administrator                Monitor services, credentials,
                                      executions, and failures
  -----------------------------------------------------------------------

## 5. High-Level Architecture

``` mermaid
flowchart TD
    A["Website Form / Email / WhatsApp"] --> B["n8n Webhook or Trigger"]
    B --> C["Validate, Normalize, and Deduplicate"]
    C --> D["AI Qualification Service"]
    D --> E["Schema Validation"]
    E --> F["Deterministic Lead Scoring"]
    F --> G["Property Matching"]
    G --> H["Odoo CRM API / Custom Module"]
    H --> I["Assignment and CRM Activities"]
    I --> J{"Priority or Exception?"}
    J -->|High priority / uncertain| K["Human Review and Notification"]
    J -->|Standard| L["Approved Follow-up Workflow"]
    K --> M["Interaction and Status Update"]
    L --> M
    M --> N["Odoo CRM"]
    N --> O["Management Reports"]
    B --> P["Execution Logs and Error Handling"]
    D --> P
    H --> P
    L --> P
```

### Architectural responsibilities

**n8n** - Receives events and starts workflows. - Coordinates API calls
and business process steps. - Applies routing, waits, schedules, and
conditional branches. - Handles retry paths, notifications, and
operational alerts. - Provides execution history for troubleshooting.

**Odoo** - Stores leads, contacts, sales stages, activities, and
ownership. - Enforces CRM business rules and permissions. - Provides the
authoritative state for sales operations. - Can be extended with custom
modules and fields.

**FastAPI + LangGraph service** - Performs complex language
understanding and AI-assisted tasks. - Produces schema-constrained
qualification results. - Uses explicitly defined tools for selected
operations. - Separates AI logic from workflow orchestration and CRM
persistence.

**PostgreSQL** - Stores application-specific records where needed, such
as property catalog data, workflow correlation IDs, and evaluation
records. - Odoo remains the source of truth for CRM entities.

**Messaging providers** - Deliver approved email or WhatsApp messages. -
Return delivery status or provider errors where supported.

## 6. Core Functional Workflows

### Workflow A --- Lead Intake and Normalization

**Trigger:** Website form submission, supported messaging event, or
manually initiated test request.

Steps:

1.  Receive the event through an n8n webhook or channel trigger.
2.  Verify required fields and validate the event shape.
3.  Normalize phone numbers, email addresses, location names, and budget
    values.
4.  Generate or preserve a correlation/idempotency key.
5.  Search Odoo for a possible existing lead or contact.
6.  Update a matching record or create a new lead according to
    configured rules.
7.  Record the intake source and event timestamp.
8.  Send invalid or incomplete payloads to an exception path rather than
    silently dropping them.

Example incoming inquiry:

> I need a three-bedroom apartment in New Cairo, budget around 6--8
> million EGP, preferably ready for delivery.

### Workflow B --- AI Lead Qualification

The AI component converts free-text inquiries into a validated
structured representation.

Example output:

``` json
{
  "property_type": "apartment",
  "location": "New Cairo",
  "bedrooms": 3,
  "budget_min": 6000000,
  "budget_max": 8000000,
  "currency": "EGP",
  "delivery_preference": "ready",
  "purchase_intent": "high",
  "missing_information": ["payment_preference"],
  "needs_human_review": false
}
```

Design requirements:

-   Use a defined JSON schema or equivalent structured-output
    validation.
-   Treat customer messages and retrieved content as untrusted input.
-   Do not let extracted AI fields directly authorize sensitive actions.
-   Preserve the original inquiry for audit and review.
-   Route malformed, incomplete, or low-confidence outputs for
    clarification or human review.
-   Avoid inferring sensitive personal characteristics.

### Workflow C --- Deterministic Lead Scoring and Routing

Use transparent business rules for priority. AI may extract signals, but
the score should be calculated by deterministic application logic.

Illustrative scoring model:

  Criterion                                       Example points
  --------------------------------------------- ----------------
  Budget range provided                                       20
  Purchase timeline within three months                       30
  Property requirements sufficiently complete                 20
  Explicit high purchase intent                               20
  Customer responds to a follow-up                            10
  **Maximum**                                            **100**

Illustrative routing:

-   **80--100:** High priority; notify the assigned sales team promptly.
-   **50--79:** Standard pipeline; create a follow-up activity.
-   **0--49:** Request missing information or place into an approved
    nurture process.

Scores and thresholds are configurable examples, not validated industry
benchmarks. The system should store score components and reasons, not
only the total.

### Workflow D --- Odoo CRM Synchronization

The integration creates or updates the lead and keeps workflow state
aligned with Odoo.

Potential CRM fields:

-   Lead name and contact details.
-   Inquiry source and original message.
-   Property type, location, bedrooms, and budget.
-   Delivery preference and purchase timeline.
-   Qualification score, priority, and score explanation.
-   Assigned salesperson and sales stage.
-   Last contact time and next follow-up date.
-   Workflow correlation ID and exception status.

Implementation considerations:

-   Use the API mechanism supported by the deployed Odoo version.
-   Use a dedicated integration identity with least-privilege
    permissions.
-   Keep credentials in secure configuration, not workflow exports or
    source control.
-   Implement duplicate checks and idempotent create/update behavior.
-   Handle rate limits, timeouts, authentication failures, and
    validation errors.
-   Avoid creating a second lead when a prior request succeeded but its
    response was lost.

### Workflow E --- Property Matching

The property catalog may contain:

-   Listing identifier.
-   Property type and location.
-   Price and currency.
-   Bedrooms and bathrooms.
-   Delivery status.
-   Amenities and description.
-   Availability state and last verification time.

The first implementation can use deterministic database filters for
location, budget, bedrooms, and delivery status. Semantic retrieval can
be added for natural-language preferences after the structured baseline
is reliable.

Only properties whose availability and listing details are current
should be presented as available. If no suitable listing is found, the
workflow should ask for revised criteria or route the lead to a
representative rather than inventing options.

### Workflow F --- Customer Communication and Follow-up

Supported channels may include email and WhatsApp Business API through
an approved provider.

Example customer journey:

1.  Send a concise acknowledgement after successful lead intake.
2.  Share a relevant property shortlist only when matches are verified.
3.  Ask one or more clarification questions when required.
4.  Schedule a follow-up according to configurable business hours and
    contact rules.
5.  Stop or change the sequence when the customer replies, opts out, or
    a salesperson takes ownership.
6.  Record message status and interaction details in Odoo.
7.  Escalate delivery failures or repeated non-response according to
    configured policy.

Safeguards:

-   Respect consent, opt-out, channel policies, and applicable privacy
    requirements.
-   Apply rate limits and maximum follow-up counts.
-   Use approved message templates where required by the channel.
-   Keep human approval for sensitive or high-impact messages.
-   Do not claim a property is available, reserved, or guaranteed
    without verified data.

### Workflow G --- Human-in-the-Loop Escalation

Escalate when:

-   A lead is high priority.
-   AI output fails validation or has insufficient confidence.
-   Customer requirements conflict.
-   No suitable property is found.
-   A messaging or CRM integration repeatedly fails.
-   A customer requests a human representative.
-   An action requires approval under business policy.

The human reviewer should receive the inquiry, extracted requirements,
score explanation, matched properties, recent interactions, and the
proposed next action. The system should record the review outcome and
resume or update the workflow safely.

### Workflow H --- Reporting and Analytics

Produce daily or weekly operational summaries, such as:

-   Total leads received by source.
-   New, qualified, and disqualified lead counts.
-   Lead distribution by priority.
-   Assignment and workload by salesperson.
-   Average time from intake to first response.
-   Follow-up tasks due, completed, or overdue.
-   Property-match outcomes.
-   CRM synchronization success and failure counts.
-   Human escalation volume and reasons.
-   Workflow execution failures and recovery outcomes.

Reports should distinguish raw counts from rates and define their time
window and denominator.

## 7. Proposed Technology Stack

  -----------------------------------------------------------------------
  Layer                               Technology
  ----------------------------------- -----------------------------------
  Workflow automation                 n8n

  CRM                                 Odoo

  Custom CRM extensions               Python, Odoo modules

  AI orchestration                    LangGraph

  AI integration API                  FastAPI

  LLM                                 OpenAI API or another configurable
                                      provider

  Data store                          PostgreSQL

  API integration                     REST APIs, webhooks

  Authentication                      OAuth 2.0 or provider-supported
                                      authentication

  Communication                       Email provider, WhatsApp Business
                                      API provider

  Deployment                          Docker, Docker Compose

  Version control and CI              Git, GitHub Actions

  Testing                             Unit tests, API integration tests,
                                      workflow scenario tests

  Observability                       n8n execution history, structured
                                      logs, health checks, alerts
  -----------------------------------------------------------------------

The exact Odoo API approach, messaging provider, and LLM provider should
be selected based on the deployed versions, account permissions, and
project environment.

## 8. Reliability, Security, and Operational Design

### Reliability

-   Validate data at system boundaries.
-   Use idempotency keys for event processing.
-   Retry transient failures with bounded backoff.
-   Route permanent failures to an error workflow or dead-letter queue.
-   Prevent duplicate customer messages during retries.
-   Record correlation IDs across n8n, API services, and Odoo.
-   Provide a safe manual replay or recovery procedure.

### Security

-   Store secrets in environment variables or a dedicated secrets
    manager.
-   Use least-privilege service accounts.
-   Protect webhook endpoints with appropriate authentication and
    verification.
-   Apply access controls to CRM data and logs.
-   Avoid logging unnecessary personal information.
-   Define retention and deletion procedures for test and customer data.
-   Separate development, staging, and production credentials.

### AI safety and control

-   Validate model outputs before use.
-   Treat tool calls as actions requiring explicit authorization and
    validation.
-   Restrict AI tools to allowlisted operations.
-   Require human approval for defined high-impact actions.
-   Keep a trace of model output, validation result, and resulting
    business action.
-   Provide deterministic fallback paths when the AI service is
    unavailable.

## 9. Testing and Evaluation Plan

Use synthetic test cases before connecting real customer data.

### Functional scenarios

-   Valid new lead.
-   Existing lead with matching phone or email.
-   Missing budget or location.
-   Malformed AI output.
-   No matching property.
-   High-priority lead requiring escalation.
-   Customer opts out.
-   CRM API timeout.
-   Duplicate webhook delivery.
-   Messaging provider rejection.
-   Workflow retry after partial success.

### Metrics to report

  -----------------------------------------------------------------------
  Metric                              Definition
  ----------------------------------- -----------------------------------
  Intake success rate                 Successfully accepted valid events
                                      / valid test events

  CRM sync success rate               Successful CRM create/update
                                      operations / attempted operations

  Duplicate prevention rate           Duplicate events safely handled /
                                      duplicate events tested

  Extraction accuracy                 Correct extracted fields /
                                      evaluated fields

  Scoring consistency                 Agreement between expected rules
                                      and calculated scores

  Processing latency                  Time from event receipt to
                                      completed CRM update

  Follow-up execution rate            Follow-ups completed / follow-ups
                                      due

  Recovery success rate               Recoverable failures completed
                                      after retry / recoverable failures
                                      tested
  -----------------------------------------------------------------------

Report actual measured results, test sample size, and evaluation
conditions. Do not claim improvements in real sales conversion or
revenue without deployment evidence.

## 10. Implementation Roadmap

### Phase 1 --- Working MVP

-   Set up Odoo development environment and a test CRM.
-   Create lead intake webhook in n8n.
-   Validate and normalize incoming data.
-   Implement deterministic lead scoring.
-   Integrate Odoo lead creation and updates.
-   Add duplicate handling and email notification.
-   Add basic logs and failure paths.

### Phase 2 --- AI and sales workflows

-   Implement FastAPI qualification endpoint.
-   Add LangGraph workflow for extraction and controlled tool use.
-   Validate structured outputs.
-   Add property catalog and matching.
-   Add follow-up scheduling and CRM activity updates.
-   Add human approval and escalation paths.

### Phase 3 --- Channel integrations and reporting

-   Connect a WhatsApp sandbox or approved provider.
-   Implement opt-out and contact limits.
-   Add daily/weekly reports.
-   Add retry policies, idempotency, and recovery workflows.
-   Add workflow and API tests.

### Phase 4 --- Deployment and portfolio readiness

-   Containerize services with Docker Compose.
-   Document environment configuration and setup.
-   Add health checks and operational runbooks.
-   Record a demo using synthetic data.
-   Publish architecture, workflow screenshots, test methodology, and
    measured results.
-   Remove secrets and personal data from repository artifacts.

## 11. Expected Deliverables

-   n8n workflow exports with secrets excluded.
-   Odoo custom module(s), if required.
-   FastAPI service for AI qualification and related operations.
-   Database schema or migration files for application-specific data.
-   Docker Compose configuration.
-   Unit and integration tests.
-   Architecture and API documentation.
-   Example synthetic lead dataset.
-   Evaluation report with measured metrics.
-   Demo walkthrough showing intake, qualification, CRM synchronization,
    follow-up, escalation, and reporting.

## 12. Success Criteria

The project is considered functionally complete when a synthetic inquiry
can travel through the configured workflow from intake to CRM update and
appropriate next action, while:

-   Valid leads are structured and persisted correctly.
-   Duplicate events do not create duplicate CRM records or messages.
-   Priority decisions are explainable.
-   Uncertain or exceptional cases reach a human or safe fallback.
-   Failed integrations are logged and recoverable.
-   Communication rules and opt-outs are respected.
-   Reports reconcile with the underlying test records.
-   The setup can be reproduced from documented instructions.

## 13. CV Description

**PropFlow AI \| Autonomous Real Estate Lead Management & Sales
Automation**

-   Engineered an n8n-based automation platform integrating Odoo CRM,
    AI-powered lead qualification, deterministic scoring, property
    matching, and automated sales routing.
-   Developed LangGraph and FastAPI services for structured inquiry
    extraction, customer follow-up orchestration, human-in-the-loop
    escalation, and CRM synchronization.
-   Implemented API integration safeguards including validation,
    duplicate prevention, retry handling, execution logging, and sales
    analytics using Python and PostgreSQL.

> **CV accuracy note:** Use the description above as a target only after
> implementing the corresponding features. Replace planned capabilities
> with the functionality and measured results actually completed.

## 14. Repository Structure (Suggested)

``` text
propflow-ai/
├── README.md
├── docker-compose.yml
├── .env.example
├── docs/
│   ├── architecture.md
│   ├── api-specification.md
│   ├── workflow-catalog.md
│   ├── security-and-operations.md
│   └── evaluation-report.md
├── n8n/
│   ├── workflows/
│   └── README.md
├── odoo/
│   └── custom_addons/
├── services/
│   └── ai-qualification/
│       ├── app/
│       ├── tests/
│       └── requirements.txt
├── database/
│   └── migrations/
├── tests/
│   ├── integration/
│   └── scenarios/
└── sample-data/
    └── synthetic-leads.json
```

## 15. Summary

PropFlow AI demonstrates how workflow automation, CRM engineering, and
agentic AI can work together to support a real business process. Its
core value is not the presence of an LLM alone, but the complete,
observable workflow: capture, validate, qualify, score, match,
synchronize, communicate, escalate, and report.

The project is designed to showcase practical skills in n8n, Odoo,
LangGraph, FastAPI, APIs, OAuth-enabled integrations, and reliable
business process automation.
