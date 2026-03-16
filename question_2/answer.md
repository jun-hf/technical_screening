# Q2: Searchable Knowledge Base Chatbot for Customer Support

*System Design: Document Ingestion, Retrieval & Answer Generation*

---

## How I'd Approach This

The ask is a RAG-powered customer support chatbot — ingest documents, make them searchable via embeddings, and use an LLM to synthesize grounded answers. The architecture is well-understood at a high level, but the difference between a working demo and a production system lives in three places: chunking quality, retrieval strategy, and whether you can actually debug a bad answer when it inevitably happens.

I approach this as a **platform capability** — exposed as an internal API that chatbot UIs, agent tools, and internal search can all consume. The retrieval and generation layers are decoupled behind stable contracts so components can be upgraded independently.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                        INGESTION PIPELINE                          │
│                                                                     │
│  Sources              Processing              Storage               │
│  ┌──────────┐     ┌──────────────┐     ┌─────────────────────┐     │
│  │ PDF/DOCX │────▶│ Extract Text │────▶│ PostgreSQL          │     │
│  │ HTML/CSV │     │ Chunk (256-  │     │ (source of truth)   │     │
│  │ Zendesk  │     │  512 tokens) │     ├─────────────────────┤     │
│  │ Confluence│     │ Embed        │     │ pgvector / Milvus   │     │
│  └──────────┘     │ Quality Gate │     │ (vector index)      │     │
│       ▲           └──────────────┘     ├─────────────────────┤     │
│       │                                │ BM25 Index          │     │
│  Change Detection                      │ (keyword search)    │     │
│  (webhooks/polling)                    └─────────────────────┘     │
└─────────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────────┐
│                         QUERY PIPELINE                              │
│                                                                     │
│  ┌───────┐    ┌──────────┐    ┌──────────┐    ┌────────────────┐   │
│  │ User  │───▶│ Classify │───▶│ Retrieve │───▶│ Generate       │   │
│  │ Query │    │ Intent   │    │ (Hybrid) │    │ (LLM + Cites)  │   │
│  └───────┘    └──────────┘    └────┬─────┘    └───────┬────────┘   │
│       │            │               │                  │            │
│       │            │          ┌────┴─────┐    ┌───────┴────────┐   │
│       │            │          │ Dense    ││   │ Guardrails     │   │
│       │            │          │ + Sparse ││   │ NLI / Safety   │   │
│       │            │          │ + Rerank ││   │ Confidence     │   │
│       ▼            │          └──────────┘│   └───────┬────────┘   │
│  ┌─────────┐       │                      │           │            │
│  │ Redis   │       │                      │           ▼            │
│  │ Cache + │       │                      │    ┌──────────────┐    │
│  │ Session │       │                      │    │ Traced        │    │
│  └─────────┘       │                      │    │ Response      │    │
│                    │                      │    └──────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

### High-Level API Contract

Designing the interface first ensures we think about consumers, versioning, and backward compatibility from the start.

```
POST /v1/ask
  └─ Request:  { query, conversation_id?, filters?: { source, freshness, language } }
  └─ Response: { answer, citations: [{ chunk_id, source_doc, text_snippet, relevance_score }],
                 metadata: { confidence, retrieval_strategy, model_used, latency_ms } }

POST /v1/retrieve
  └─ Request:  { query, top_k, strategy: "hybrid" | "dense" | "sparse", filters? }
  └─ Response: { chunks: [{ id, text, score, source }] }
```

The `/retrieve` endpoint is intentionally separate from `/ask` — product teams building custom UIs or agent workflows may want raw retrieval results without LLM synthesis. This also makes debugging much easier: you can test retrieval quality independently of generation quality.

---

## 1. Document Ingestion

Ingestion is not a one-time ETL job. In a customer support context, documents change frequently — product manuals are updated, FAQs are revised, policies change mid-quarter. The pipeline must be **idempotent, incremental, and observable**.

### 1.1 Source Connectors & Text Extraction

| Source Format | Extraction Strategy | Edge Cases |
|---|---|---|
| **PDF** | PyMuPDF for text-based; Tesseract OCR for scanned with Malay language pack | Mixed scanned/digital pages; multi-column layouts in product manuals |
| **HTML/Zendesk/Confluence** | BeautifulSoup + trafilatura for content extraction; boilerplate removal | Navigation cruft, bilingual help centers with mixed EN/BM content |
| **DOCX** | python-docx; LibreOffice headless for legacy .doc | Tracked changes, embedded tables containing key troubleshooting steps |
| **Plain Text / CSV** | Encoding detection (chardet); Unicode normalization (NFC) | Mixed encodings from legacy systems |

Each source type gets a dedicated connector that handles auth, pagination, and **change detection** (webhooks where available, ETag/timestamp polling otherwise). This keeps parsing logic separate from chunking logic and ensures we only reprocess what's actually changed.

**Deduplication:** Content-hash at the document level prevents reprocessing unchanged documents. At the paragraph level, near-duplicate detection (MinHash/LSH) catches content that's been reorganized across pages but not meaningfully changed — common in support docs where the same troubleshooting steps appear in multiple articles.

### 1.2 Chunking Strategy

This is the **highest-leverage decision** in the entire pipeline, and the one most teams get wrong by defaulting to fixed-size token splits.

I would implement a **semantic-structural hybrid** approach, targeting **256–512 tokens per chunk** (tuned empirically — too small loses context, too large dilutes the relevance signal during retrieval):

- **Structural boundaries first:** Respect document structure — headings, sections, list groups, FAQ question-answer pairs. Never split a coherent thought mid-paragraph. A FAQ entry like "Q: How do I reset my password? A: Go to Settings > ..." should always be a single chunk.
- **Context bridging over naive overlap:** Instead of repeating the last N tokens in the next chunk, attach the **heading hierarchy as a context prefix** (e.g., `"Product X > Troubleshooting > Wi-Fi Issues: ..."`). This gives the retriever context without wasting embedding capacity on duplicated content.
- **Chunk metadata:** Every chunk carries: `source_doc_id`, `chunk_index`, `heading_path`, `version`, `content_hash`, `created_at`. This metadata is critical for three things: citation in answers, freshness ranking during retrieval, and incremental re-indexing when documents update.

**For YTL AI Labs specifically:** Customer support content for Malaysian products will contain mixed BM/EN text — Malay UI labels with English technical terms, Manglish in community-sourced FAQs. Sentence boundary detection must handle language switches within a paragraph. The chunking module should be a **shared library** in the monorepo, not an inline implementation — RAG, document summarization, and search indexing all need the same logic.

### 1.3 Embedding & Indexing

- **Dual representation:** Each chunk is stored with both a dense embedding (for semantic search) and BM25 sparse tokens (for keyword matching). This enables the hybrid retrieval strategy in Section 2.
- **Embedding model selection:** I would start with a strong multilingual model (Cohere embed-v3 or similar), but design the pipeline so the embedding model is a **swappable configuration**. When ILMU's embedding capabilities are production-ready, switching should be a config change + re-index job, not a code change. A sovereign model trained on Malaysian data will produce better representations for local content than a generic multilingual encoder.
- **Write path:** Chunks are written to both the vector store and a metadata table (PostgreSQL) in a single transaction. The metadata store is the **source of truth**; the vector index is a derived, rebuildable artifact. If the index gets corrupted or the embedding model changes, we rebuild from the metadata store.

### 1.4 Quality Gate

Before chunks enter the serving index, automated validation checks:

- Embedding dimensions and norms are within expected ranges (catches model version mismatches during deployment)
- Chunk length is within configured bounds (catches parser failures — a zero-length chunk or a 50k-token chunk indicates extraction went wrong)
- No PII detected in chunks marked as public-facing
- A sample of chunks from each batch is evaluated against known queries to verify retrieval quality hasn't regressed

Most RAG tutorials skip this entirely. In production, a single bad batch of embeddings (wrong model version, corrupted parser output) silently degrades the entire system. The quality gate is cheap insurance.

---

## 2. Storage & Retrieval

### 2.1 Storage Architecture

| Store | Technology | Purpose | Why Separate |
|---|---|---|---|
| **Vector store** | pgvector (start) → Milvus (at scale) | ANN dense similarity search | Optimized for approximate nearest neighbor; scales independently |
| **Document store** | PostgreSQL | Chunk text, metadata, versioning, lineage | Source of truth; supports ACID, complex queries, joins |
| **Keyword index** | PostgreSQL FTS or Elasticsearch | BM25 sparse retrieval | Catches exact-match queries that embeddings miss |
| **Cache** | Redis | Query result caching, session state | Sub-10ms for repeated/similar queries |

### 2.2 Retrieval Strategy: Hybrid Search + Re-ranking

Single-method retrieval is the most common failure mode in production RAG. Dense embeddings miss exact terms — product SKUs, error codes, policy numbers. Keyword search misses semantic paraphrases ("can't connect to internet" vs "Wi-Fi not working"). You need both.

**Step 1 — Parallel retrieval (target: <100ms):**
- Dense path: query embedding → ANN search in vector store → top-20 candidates
- Sparse path: BM25 query → keyword index → top-20 candidates
- Both execute concurrently; results merged via **Reciprocal Rank Fusion (RRF)**. This produces ~30 unique candidate chunks.

**Step 2 — Cross-encoder re-ranking (target: <200ms):**
- The merged candidate set is scored by a cross-encoder model that evaluates query-chunk relevance with full attention over the pair.
- Cross-encoders are 10-50x more accurate than bi-encoder cosine similarity for relevance judgments. The latency cost is acceptable because the candidate set is small.
- Top 5-8 re-ranked chunks are passed to the generation stage.

**Step 3 — Metadata filtering & freshness:**
- Hard filters applied before re-ranking: document access permissions, content freshness (prefer latest version), source trust scores.
- When a FAQ is updated, the old version should not compete with the new one in retrieval. The `version` and `content_hash` metadata from the ingestion pipeline makes this possible.

### 2.3 Provider Abstraction

```python
class RetrievalProvider(Protocol):
    async def search_dense(self, embedding: list[float], top_k: int, filters: dict) -> list[Chunk]: ...
    async def search_sparse(self, query: str, top_k: int, filters: dict) -> list[Chunk]: ...
    async def rerank(self, query: str, chunks: list[Chunk], top_k: int) -> list[Chunk]: ...

class PgVectorProvider(RetrievalProvider): ...   # Start here
class MilvusProvider(RetrievalProvider): ...     # Migrate when scale demands
```

Product teams consume `/v1/retrieve` — they never import Milvus or Elasticsearch clients directly. If we swap vector backends (and at the pace AI tooling evolves, we will within 6-12 months), the API contract doesn't change. This is the core platform engineering value-add.

---

## 3. Ensuring Fast & Accurate Answers

### 3.1 Generation Pipeline

**Query understanding layer:**
- Before retrieval, classify the query intent — factual lookup, how-to, troubleshooting, or conversation continuation. This informs both retrieval strategy (simple lookups can skip re-ranking) and prompt template selection.
- For multi-turn conversations, resolve coreferences and expand the query with session context before sending to retrieval. "What about for the Pro model?" needs the previous query's product context. Conversation history is stored in **Redis** (keyed by `conversation_id`, TTL of 24 hours), with long-term session logs persisted to PostgreSQL for analytics. This keeps the hot path fast while preserving data for quality analysis.
- **Language handling:** If a user asks in Manglish but the knowledge base is in formal English, the system should still retrieve relevant docs. A lightweight query expansion step (using ILMU) bridges this gap by generating both BM and EN query variants.

**Grounded generation with citations:**

The LLM receives a structured prompt that enforces grounding and citation. Example template:

```
SYSTEM:
You are a customer support assistant for YTL products.
Answer the user's question using ONLY the context chunks below.
For every claim, cite the source as [chunk_id].
If the context does not contain enough information, respond:
"I don't have enough information to answer this. Let me connect you with a support agent."
Never guess or fabricate information.

CONTEXT:
{% for chunk in chunks %}
[{{ chunk.id }}] (source: {{ chunk.source_doc }})
{{ chunk.text }}
{% endfor %}

USER: {{ query }}
```

- Citations are post-processed: each claim is mapped back to its source chunk. The response includes references to the original documents so users can verify.
- A lightweight NLI check validates that each cited claim is actually entailed by its source chunk before the response is returned.

**Guardrails & output validation:**

| Check | What It Catches | Action |
|---|---|---|
| **NLI faithfulness** | Claims not entailed by retrieved chunks | Flag or strip unsupported claims |
| **Safety filtering** | Content policy violations | Block response; return safe fallback |
| **Confidence scoring** | Low retrieval scores + inconsistent answer | Trigger human handoff |
| **Language consistency** | Response language doesn't match user's query language | Re-generate with corrected language instruction |

### 3.2 Latency Budget

| Stage | Target | Optimization |
|---|---|---|
| Query understanding | <50ms | Lightweight classifier; cached intent patterns |
| Retrieval (parallel) | <100ms | Pre-warmed connections; ANN index in memory |
| Re-ranking | <200ms | Quantized cross-encoder; batched inference |
| LLM generation | Stream first token <500ms | SSE streaming via vLLM/TGI |
| **Total (first token)** | **<800ms** | Streaming means the user sees the answer forming immediately |

**Semantic caching:** Cache not just exact query matches but semantically similar ones (embedding distance below threshold). Huge win for support chatbots where hundreds of users ask slight variations of the same question daily.

**Tiered retrieval:** For simple factual lookups (detected at intent classification), skip the expensive cross-encoder re-ranking step. Save the full pipeline for complex or ambiguous queries.

### 3.3 Cost Management

LLM token costs scale linearly with traffic. Left unmanaged, they dominate operational spend.

| Strategy | Impact | Implementation |
|---|---|---|
| **Semantic caching** | 30–50% fewer LLM calls for support chatbots (high query overlap) | Redis + embedding similarity threshold |
| **Tiered model routing** | Use a smaller/cheaper model for simple factual lookups; reserve the large model for complex queries | Intent classifier gates model selection |
| **Token budget per query** | Cap context window usage; pass only top-K re-ranked chunks, not all candidates | Configurable `max_context_tokens` per endpoint |
| **Prompt compression** | Summarize long chunks before injection when context is tight | Lightweight summarization pass on chunks exceeding token threshold |

Token usage and cost-per-query are tracked per request in the observability trace, enabling per-feature and per-team cost attribution.

### 3.4 Deployment & Scaling

| Component | Deployment | Scaling Strategy |
|---|---|---|
| **Ingestion workers** | Celery / Temporal workers behind a task queue | Scale horizontally by document volume; isolate from serving path |
| **Retrieval API** | Containerized (Docker/K8s), stateless | Auto-scale on request latency (P95); vector index loaded in memory |
| **Generation API** | Separate service fronting LLM providers | Scale independently; rate-limit per consumer to prevent noisy-neighbor |
| **Vector store** | pgvector (single-node start) → Milvus cluster | Migrate when index exceeds single-node memory; read replicas for query load |
| **Redis** | Managed Redis (ElastiCache or equivalent) | Session + cache layer; eviction policy: LRU with semantic TTL |

Key principle: **ingestion and serving scale independently**. A bulk re-index of 100K documents should never degrade query latency for end users. The ingestion pipeline writes to a staging index; once quality gates pass, an atomic alias swap promotes it to the serving index (blue-green for the vector store).

### 3.5 Evaluation & Feedback Loop

Accuracy is not a static property — it's a metric you measure and improve continuously.

**Automated metrics (run on every request):**

| Metric | Purpose | Notes |
|---|---|---|
| **Retrieval Recall@K** | Are the right chunks being retrieved? | Track per query category; alert on regression |
| **NLI faithfulness** | Per-claim entailment against source chunks | Most reliable hallucination detector |
| **LLM-as-Judge** | Coherence, helpfulness, and groundedness scored by a second LLM | Structured rubric, 1-5 per dimension, returned as JSON |
| **Confidence score** | Composite of retrieval scores + answer consistency | Routes low-confidence to human handoff |

**Online signals:**
- Thumbs up/down (explicit feedback)
- Follow-up query rate — if a user immediately rephrases the same question, the first answer likely failed (implicit signal)
- Human handoff rate
- Citation click-through — high click-through may indicate low trust in the answer

**Offline evaluation:**
- **Golden dataset** of query-answer pairs maintained by domain experts. Every pipeline change is regression-tested against it.
- **LLM-as-Judge evaluation** run nightly on a sample of production traffic to detect quality drift.
- **A/B testing pipeline:** New retrieval strategies, prompt templates, or re-ranker models are tested with live traffic before full rollout.

### 3.6 Production Observability

Every query produces a **trace** capturing: original query → classified intent → retrieved chunks with scores → re-ranked order → prompt sent to LLM → generated response → confidence score → user feedback (if given).

This trace is the debugging unit. When a support agent reports a bad answer, an engineer pulls the trace and can immediately see whether the failure was in retrieval (wrong chunks returned), re-ranking (right chunks scored low), or generation (right context, bad synthesis). Without this, debugging RAG systems is guesswork.

**Key dashboards:**
- Retrieval hit rate and relevance score distribution
- Answer quality score trend (daily, from LLM-as-Judge)
- Latency percentiles by stage (P50, P95, P99)
- Index freshness — how old is the oldest document in the serving index?
- Token usage and cost per query

---

> **Why ILMU matters here:** A sovereign Malaysian LLM that natively understands Bahasa Melayu, Manglish, and dialectal patterns is the ideal primary model for both retrieval query expansion and answer generation. It eliminates many explicit language-handling workarounds because the model inherently understands Malaysian language patterns. I would design the system to use ILMU as the default model with fallback to other providers for specific edge cases — all configurable via feature flags behind the provider abstraction, not hardcoded.

---

*This design reflects how I approach platform engineering: start with the API contract and consumer needs, build modular components behind stable abstractions, invest in observability from day one, and design for the failure modes that production traffic will inevitably surface. The multilingual dimension — handling BM, English, and Manglish queries against a mixed-language knowledge base — is not a bolt-on but a first-class design constraint, which is exactly what building for Malaysian users demands.*