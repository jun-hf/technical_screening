# Technical Screening — YTL AI Labs Backend Platform Engineer

## Repository Structure

### Question 1: LLM Output Validator (Coding)
Validate and coerce untrusted JSON from an LLM against a strict tool-call schema.

| File | Description |
|------|-------------|
| `question_1/question.md` | Problem statement and target schema |
| `question_1/design.md` | Design notes, threat model, and trade-off rationale |
| `question_1/validator.py` | Implementation |
| `question_1/validator_test.py` | Test suite |
| `question_1/pyproject.toml` | Project config (uses `uv` + `pytest`) |

### Question 2: Knowledge Base Chatbot (System Design)
High-level design for a searchable customer-support chatbot using an LLM.

| File | Description |
|------|-------------|
| `question_2/quetion.md` | Problem statement |
| `question_2/answer.md` | Full system design write-up |

### Question 3: Multilingual Summarization (System Design)
Architecture for an English-Malay document summarization system.

| File | Description |
|------|-------------|
| `question_3/question.md` | Problem statement |
| `question_3/answers_v3.md` | System design and architecture |
| `question_3/evaluation_report.md` | Evaluation methodology and metrics |

### Perspectives
Reviewer-perspective guides that frame each answer from different engineering viewpoints.

| File | Viewpoint |
|------|-----------|
| `perspectives/ai_ml_research_engineer.md` | AI/ML Research Engineer |
| `perspectives/backend_platform_lead.md` | Backend Platform Lead |
| `perspectives/hiring_bar_raiser.md` | Hiring Bar Raiser |
| `perspectives/product_engineering_manager.md` | Product Engineering Manager |
| `perspectives/sre_infrastructure_lead.md` | SRE / Infrastructure Lead |

## Running Question 1 Tests

```bash
cd question_1
uv sync
uv run pytest validator_test.py -v
```
