# The Open-Source Register

Every tool from the `04.md` survey, with a verdict and the trigger that changes
it. This exists so "are we using the ecosystem?" has an auditable answer, the
same way `enforcement.py` answers "are we covering what IFSCA enforces?"

The survey's own conclusion is the operating rule here: *"I would NOT install
everything above — that would be a disaster… startup architecture by
GitHub-star accumulation."* Tools are adopted at **boundaries**, when something
real consumes them; the core stays standard-library and deterministic. Note
that adopting a tool does not always mean importing a package — the two in use
today cost zero dependencies, because what we adopted is their *protocol* and
*vocabulary*.

## In use now

| Tool | How it is used |
|---|---|
| **OpenSanctions / yente** | **Self-hosted**: portable Elasticsearch + yente in a venv, no Docker, no admin — `selfhost/yente.ps1 start`, indexing the consolidated `sanctions` collection per `selfhost/manifest.yml`. `vinzor/screening.py` speaks the yente `/match` protocol via stdlib `urllib`; the same adapter works unchanged against OpenSanctions' hosted API. Hits mint `SCREENING_COMPLETED` facts with full provenance (service, query, score, datasets); a clean screen is recorded too, because "we checked and found nothing" is the clause 5.9 evidence an inspector asks for. Tested offline against canned protocol responses. |
| **Azure OpenAI** | The drafting model behind `assist.py`, reached through `azure.py` over stdlib `urllib` — one dated API version, JSON-mode replies, the key from the environment and nowhere else. **India regions only**, enforced against an allowlist before the first call and against the `x-ms-region` header on every reply, because a Global Standard deployment routes wherever there is capacity. Spend is capped and the running total is summed from the log, so the cap cannot drift. Tested entirely offline against an injected HTTP call. |
| **Amazon Bedrock** | The drafting model where this is deployed, through `bedrock.py` over stdlib `urllib` — the Converse API, so the model is a setting rather than a parser. SigV4 is signed by hand: `boto3` would do it, and it is a large dependency in the audit path of a system whose core has none. **India only, and here that costs something real.** In `ap-south-1` every Anthropic model is offered only through a cross-region inference profile, which routes to whichever Asia-Pacific region has capacity, so the adapter refuses profiles by prefix and the product runs on a weaker model than it could. Enforced again by the instance role, which grants only `arn:aws:bedrock:ap-south-1::foundation-model/*` — a shape no inference profile can match. Credentials come from the instance role over IMDSv2; there is no key. Tested entirely offline against an injected HTTP call. |
| **FollowTheMoney** | The wire vocabulary of that adapter: our `EntityKind`s map to FTM schemata (`Person`, `Company`, `LegalEntity`) once, at the boundary, in `FTM_SCHEMA`. The core never learns FTM exists. |
| **UK Companies House** | `vinzor/registries.py`'s `lookup_company_uk` tool, offered to the assistant alongside `screening`. Free, official, and unlimited for the company profile and PSC lookups it makes — no key required, mirroring the same stdlib `urllib` shape as the yente adapter. UK companies only; see OpenCorporates below for everywhere else. |
| **OpenCorporates** | The same module's `lookup_company` tool, for companies outside the UK. Free tier capped at 50 requests/day and needs an API token, read from `VINZOR_OPENCORPORATES_TOKEN` exactly as `bedrock.py` and `azure.py` read theirs — absent, the tool says so plainly rather than returning nothing. |

## Earmarked — adopted when the trigger fires

| Tool | Trigger |
|---|---|
| **Azure Document Intelligence** | Same trigger as Docling, and now a live candidate: the Azure credits are Azure-wide, not model-only. Benchmark the two on the first real KYC pack — Docling costs nothing and runs locally, which matters for data that never should have left the building. |
| **Docling** | First real KYC pack to extract. Becomes an adapter minting `ENTITY_REGISTERED` / `OWNERSHIP_DECLARED` facts with `basis` provenance, exactly as `seed.py` does for CSVs. Benchmark **Unstructured** against it then, not before. |
| **Presidio** | *Trigger re-examined, deliberately not fired.* Customer data now does flow to a model — but redacting names is wrong for a name-matching task, and the data never leaves India. What replaced it is narrower and stronger: the model is handed a **computed comparison**, not the file, and every figure it writes back is checked against what it was given. Adopt Presidio when data flows to a provider *outside* our residency boundary, or for a task where identity is not the point. |
| **Outlines** | *Partly satisfied.* Azure's JSON mode plus `parse_reply`'s validation covers the drafting seam today, with no dependency. Adopt when a schema grows past what one validation function should hold, or when a model without native JSON mode is used. |
| **LangGraph / MCP / Agent Skills** | *Seam now built and none of them needed for it* — the drafting boundary is one function call, and reaching for a graph runtime to hold one call would be the tail wagging the dog. Reconsider at agents 2–5 of SPEC-001, if they genuinely chain. MCP to expose the engine's reads as tools; skills for IFSCA-specific drafting; LangGraph only if the workflows genuinely become long-running and stateful. |
| **nomenklatura / rigour / zavod** | If watchlist ingestion moves in-house — today we query a service; these matter when we *maintain* merged lists ourselves with lineage. |
| **OpenAleph** | When document collections exist to investigate across. Depends on the Docling trigger firing first. |
| **AMLSim / Tide** | When transaction anomaly detection moves in-house. Today anomalies arrive labelled in the dataset; the day we detect them ourselves, these generate the labelled laundering patterns to benchmark against. |
| **Temporal** | A workflow that genuinely waits days on the outside world (document requests, external approvals) *and* more than one process. The event log currently carries that state fine. |
| **Prefect / Dagster** | Scheduled data pipelines — recurring watchlist pulls, corpus refreshes. Pick one then; both is a smell. |
| **Postgres + pgvector** | Concurrent writers or a real read load; `eventlog.py` is one module to port. pgvector rides along when semantic retrieval over documents exists. |
| **Elasticsearch** | *Trigger fired*: arrived with self-hosted yente, as predicted — a portable single node on :9200, used by yente alone. Still not adopted by the core, and it should stay that way. |
| **OpenBB** | The fund-intelligence layer, if the product ever expands past compliance into portfolio context. Far trigger. |

## Reference — studied, informing the design, never imported

| Tool | What it contributed |
|---|---|
| **OpenFisca** | Proof that rules-as-code is a real paradigm. We kept the idea and inverted one part: their rules recompute history under current law; our findings are recorded facts precisely so history *cannot* recompute (DESIGN.md, decision 2). |
| **Ballerine** | Workflow shapes for configurable onboarding — relevant when a customer needs to author flows. |
| **ADGM Regulatory KG / ComplianceNLP papers** | The regulatory-graph architecture, for when the clause register outgrows a hand-curated file. Today, 21 clauses fit in one reviewable module — which is a feature. |
| **Fineract / ERPNext** | Domain-model reference for financial systems. Study, never build on. |

## Rejected for now

| Tool | Why |
|---|---|
| **Neo4j** | The ownership graph is ~50 edges; an adjacency map resolves UBO in microseconds. Re-open at thousands of entities per workspace. |
| **OpenAI Agents SDK** | No agent runtime exists to need it; if one does, MCP is the interoperable seam and the model provider stays swappable. |
| **A rules DSL of any kind** | Two engines and an `eval()` died in the previous build. A customer-authored rule language returns as a restricted grammar behind the `Finding` contract, when a paying customer needs it. |
