# ANIMA-RAG-Lab — Task 0.1

Emergency veterinary data ingestion and RAG triage pipeline for **AnimaLink**. Harvests Merck Veterinary Manual emergency/poisoning content, structures it for fast Red-Light physiologic checks, and serves retrieval-augmented triage answers.

## Architecture

```
Merck Manual (live or seed)
        │
        ▼
01_scrape_merck.py          → data/raw/merck_emergencies_raw.json
        │
        ▼
02_process_merck.py         → data/processed/merck_emergencies_processed.json
                            → data/triage_tree/merck_red_light_metrics.json
        │
        ▼
03_red_light_intercept.py   → fast RED/YELLOW/GREEN gate (<500 ms, no LLM)
        │
        ▼
04_chunk_merck.py           → data/processed/merck_emergencies_chunks.json
        │
        ▼
05_embed_merck.py           → data/processed/merck_vector_store/
        │
        ▼
06_rag_query.py             → CLI / JSON pipeline
07_api_server.py            → POST /triage/query (FastAPI)
```

**Safety flow:** Red-Light runs first. If status is `RED`, the pipeline intercepts and returns emergency guidance without vector search or LLM calls.

## Quick start

```bash
cd anima-rag-lab
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Offline mode (recommended if Merck is blocked)

Merck CloudFront may return **HTTP 403** from some networks/regions. Use curated seed data:

```bash
python scripts/01_scrape_merck.py --seed
python scripts/02_process_merck.py
python scripts/04_chunk_merck.py
python scripts/05_embed_merck.py
```

### Run the API + frontend demo

**One-click（推荐演示用）：**

```bash
./scripts/run_demo.sh
```

或手动：

```bash
python scripts/07_api_server.py
```

Then open:

| URL | Purpose |
|-----|---------|
| http://127.0.0.1:8000/ | **AnimaLink triage demo UI** |
| http://127.0.0.1:8000/docs | Swagger API docs |
| http://127.0.0.1:8000/health | Health check |

In the UI: pick an example（正常 / 中暑 / 巧克力 / 中毒）→ click **开始分诊**.  
结果区会显示 **红 / 黄 / 绿灯白话说明**。

**团队演示脚本：** 见 [`docs/DEMO_GUIDE.md`](docs/DEMO_GUIDE.md)（5–8 分钟口播 + 检查清单）。  
**App 对接契约：** 见 [`docs/APP_INTEGRATION.md`](docs/APP_INTEGRATION.md)（`POST /v1/triage/query`）。  
**App 客户端样例：** 见 [`examples/app_clients/`](examples/app_clients/)（Swift / Kotlin / TypeScript）。

### Run tests

```bash
pytest tests/ -v
```

### Run triage eval suite

Fixed regression cases（心率 / 中暑 / 中毒 / 巧克力·葡萄 / 舔脚 / 百合 / 超范围等）:

```bash
python scripts/09_run_eval.py
# or via pytest
pytest tests/test_eval_suite.py -v
```

Report writes to `evals/last_report.json`. LLM is off by default for determinism; pass `--with-llm` to exercise OpenAI answers.

## Pipeline scripts

| Step | Script | Output |
|------|--------|--------|
| 0.1 Scrape Merck | `scripts/01_scrape_merck.py` | `data/raw/merck_emergencies_raw.json` |
| 0.2 ASPCA toxic plants | `scripts/10_scrape_aspca_toxic.py` | `data/raw/aspca_toxic_plants_raw.json` + `data/triage_tree/aspca_toxic_plants.json` |
| 0.3 Complaint→clinical map | `scripts/11_build_complaint_map.py` | `data/processed/complaint_clinical_map.csv` + `data/triage_tree/complaint_clinical_map.json` |
| Process Merck | `scripts/02_process_merck.py` | `data/processed/merck_emergencies_processed.json` |
| Red-Light metrics | (same script) | `data/triage_tree/merck_red_light_metrics.json` |
| Red-Light | `scripts/03_red_light_intercept.py` | demo CLI (+ ASPCA plant match) |
| Chunk | `scripts/04_chunk_merck.py` | `data/processed/merck_emergencies_chunks.json` |
| Embed | `scripts/05_embed_merck.py` | `data/processed/merck_vector_store/` |
| RAG query | `scripts/06_rag_query.py` | CLI / `--json` stdin |
| API | `scripts/07_api_server.py` | FastAPI server |
| Eval | `scripts/09_run_eval.py` | `evals/last_report.json` |

### 01 — Scrape

```bash
# Live scrape via international MSD Vet Manual (default, 10 articles)
python scripts/01_scrape_merck.py

# Full crawl of emergency/poisoning + owner clinical sections (incremental merge)
python scripts/01_scrape_merck.py --full

# Rebuild from scratch instead of merging with existing raw JSON
python scripts/01_scrape_merck.py --full --replace

# Offline seed (no network)
python scripts/01_scrape_merck.py --seed
```

### 10 — ASPCA toxic plants (Task 0.2)

```bash
# Live scrape dog + cat toxic plant lists
python scripts/10_scrape_aspca_toxic.py

# Offline high-risk seed
python scripts/10_scrape_aspca_toxic.py --seed
```

Builds ~400+ toxic plants / ~1000 aliases into `data/triage_tree/aspca_toxic_plants.json`.  
Red-Light matches plant names (plus Chinese aliases for high-risk items) for absolute RED intercept. Short/ambiguous food names (e.g. apple) require an ingestion cue (`ate` / `吃了`).

### 11 — Complaint → clinical map (Task 0.3)

```bash
# HuggingFace pet-health-symptoms + curated ZH/EN lexicon
python scripts/11_build_complaint_map.py

# Curated lexicon only (offline)
python scripts/11_build_complaint_map.py --seed-only

# Also pull Kaggle animal-disease (requires ~/.kaggle/kaggle.json)
python scripts/11_build_complaint_map.py --with-kaggle
```

Writes `complaint_clinical_map.csv` mapping owner phrases (e.g. 「吐黄水」) to clinical retrieval terms (`bilious vomiting`, `gastroenteritis`, …). The RAG pipeline expands these into the retrieval query automatically.

**Sources merged by default when available:**
1. Curated bilingual lexicon  
2. HuggingFace `karenwky/pet-health-symptoms-dataset`  
3. Kaggle-schema **Animal Condition Classification** (`gracehephzibahm/animal-disease`) — via official API, local CSV, or public mirror

```bash
# Force include / refresh Kaggle-schema data
python scripts/11_build_complaint_map.py --with-kaggle

# Or point at a downloaded CSV
python scripts/11_build_complaint_map.py --kaggle-csv data/raw/kaggle_animal_disease/data.csv
```

To use the official Kaggle API: put credentials in `~/.kaggle/kaggle.json` (from https://www.kaggle.com/settings), then `--with-kaggle`.

**Default base URL:** https://www.msdvetmanual.com  
(US/Canada mirror https://www.merckvetmanual.com may return 403 outside North America.)

Override if needed:

```bash
export MERCK_BASE_URL=https://www.msdvetmanual.com
```

**Category paths:**
- `/emergency-medicine-and-critical-care`
- `/special-pet-topics/emergencies`
- `/special-pet-topics/poisoning`

### 02 — Process

Extracts `vital_signs`, `toxic_dosages`, `triage_indicators`, and `numeric_metrics` for Red-Light triage.

```bash
python scripts/02_process_merck.py
```

### 03 — Red-Light intercept

```bash
python scripts/03_red_light_intercept.py
```

Evaluates vitals/symptoms against Merck reference metrics. Target latency: **< 500 ms**.

### 04 — Chunk

Builds dense RAG chunks (paragraph, triage, vital, toxic, metric types).

```bash
python scripts/04_chunk_merck.py
```

### 05 — Embed

Builds a local TF-IDF vector store (default, no API key required).

```bash
python scripts/05_embed_merck.py
```

### 06 — RAG query (CLI)

```bash
python scripts/06_rag_query.py

# JSON stdin mode
echo '{"question":"What is normal heart rate for a small dog?","species":"dog","size":"small","heart_rate_bpm":95}' \
  | python scripts/06_rag_query.py --json
```

## API reference

### `GET /health`

Returns service and vector store status.

### `POST /triage/query`

**Request body:**

```json
{
  "question": "What is normal heart rate for a small dog?",
  "species": "dog",
  "size": "small",
  "heart_rate_bpm": 95,
  "crt_seconds": 1.5,
  "rectal_temp_f": 101.8,
  "symptoms": ["lethargy"],
  "chief_complaint": "Owner worried after exercise",
  "top_k": 5
}
```

**Response fields:**

| Field | Description |
|-------|-------------|
| `red_light_status` | `RED`, `YELLOW`, or `GREEN` |
| `intercepted` | `true` if Red-Light blocked LLM/retrieval |
| `answer` / `answer_zh` | Chinese triage guidance (UI primary) |
| `answer_en` | English triage guidance (always stored) |
| `recommendation_zh` / `recommendation_en` | Red-Light bilingual recommendations |
| `record_id` | SQLite row id after persistence |
| `sources` | Retrieved Merck chunks (empty if intercepted) |
| `elapsed_ms` | Total pipeline time |

Every `POST /triage/query` is saved to SQLite (`data/triage_results.db` by default) with **both** `answer_zh` and `answer_en`.

- `GET /triage/results?limit=20` — recent records
- `GET /triage/results/{record_id}` — one record

**Example:**

```bash
curl -X POST http://127.0.0.1:8000/triage/query \
  -H "Content-Type: application/json" \
  -d '{
    "question": "What should I do for heat stroke?",
    "species": "dog",
    "rectal_temp_f": 105.2,
    "chief_complaint": "Heat stroke after hiking, collapse"
  }'
```

## Environment variables

| Variable | Default | Purpose |
|----------|---------|---------|
| `MERCK_USE_SEED` | — | Set `1`/`true` to force seed mode in scraper |
| `MERCK_EMBEDDER` | `sentence_transformers` | `tfidf` or `sentence_transformers` |
| `MERCK_EMBED_MODEL` | `paraphrase-multilingual-MiniLM-L12-v2` | Sentence-transformers model name |
| `OPENAI_API_KEY` | — | Enables LLM answers in RAG (optional) |
| `ANIMA_LLM_MODEL` | `gpt-4o-mini` | OpenAI model for answer generation |
| `ANIMA_API_HOST` | `127.0.0.1` | API bind host |
| `ANIMA_API_PORT` | `8000` | API bind port |
| `ANIMA_TRIAGE_DB` | `data/triage_results.db` | SQLite path for bilingual triage history |

## Merck / MSD 403 workaround

- **US/Canada site** https://www.merckvetmanual.com may return **403** outside North America.
- **International site** https://www.msdvetmanual.com has the same content and is the scraper default.
- If both fail, use seed mode:

   ```bash
   python scripts/01_scrape_merck.py --seed
   ```

The seed file `data/raw/merck_emergencies_seed.json` contains 5 curated emergency/poisoning articles with triage vitals and tables.

## Data artifacts

```
data/
├── raw/
│   ├── merck_emergencies_raw.json      # scraped or seeded articles
│   └── merck_emergencies_seed.json     # offline fallback source
├── processed/
│   ├── merck_emergencies_processed.json
│   ├── merck_emergencies_chunks.json
│   └── merck_vector_store/
│       ├── vectors.npy
│       ├── records.json
│       ├── manifest.json
│       └── tfidf_model.json
└── triage_tree/
    └── merck_red_light_metrics.json    # fast physiologic checks
```

## Testing

```bash
pytest tests/ -v
```

| Suite | Coverage |
|-------|----------|
| `test_red_light.py` | RED/YELLOW/GREEN cases, <500 ms budget |
| `test_retrieval.py` | Vector search relevance |
| `test_pipeline.py` | Full RAG integration |
| `test_api.py` | FastAPI endpoints |
| `test_eval_suite.py` | Fixed demo regressions (`evals/cases.json`) |
| `09_run_eval.py` | CLI eval runner + `evals/last_report.json` |

## Troubleshooting

| Issue | Fix |
|-------|-----|
| Merck 403 | Use `--seed`; retry live scrape with VPN later |
| `Saved 0 articles` | Network blocked; run with `--seed` |
| Empty vector store | Run `04_chunk_merck.py` then `05_embed_merck.py` |
| API 503 | Ensure vector store exists; restart API after embedding |
| LibreSSL warning | Harmless on macOS; does not affect pipeline |
| No LLM answers | Set `OPENAI_API_KEY`; otherwise extractive fallback is used |

## Optional upgrades

**Semantic embeddings (default via `.env`):**

```bash
# already set in .env:
# MERCK_EMBEDDER=sentence_transformers
# MERCK_EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2
python scripts/05_embed_merck.py
```

Fallback to TF-IDF:

```bash
MERCK_EMBEDDER=tfidf python scripts/05_embed_merck.py
```

**OpenAI answers (recommended for GREEN/YELLOW quality):**

```bash
cp .env.example .env
# edit .env and set OPENAI_API_KEY=sk-...
python scripts/07_api_server.py
```

UI top bar shows `LLM：已开启 · gpt-4o-mini` when the key is loaded.  
RED intercept never calls OpenAI. If the key is missing or the call fails, the pipeline falls back to local extractive Chinese/English answers.

Without a key:

```bash
# LLM stays off — extractive_fallback
python scripts/07_api_server.py
```

## Project status

**Lab status: Module A (emergency triage data + Red-Light + RAG API) is complete and ready to hand off to AnimaLink.**  
See [`docs/MERGE_TO_ANIMALINK.md`](docs/MERGE_TO_ANIMALINK.md).

Task 0.1 pipeline is complete and knowledge base expanded:

- [x] Scrape / seed ingestion (MSD emergency + owner sections)
- [x] ASPCA toxic plant list for Red-Light matching (Task 0.2)
- [x] Owner complaint → clinical term map (Task 0.3)
- [x] App integration contract (`/v1/triage/query` + API key)
- [x] Structured processing + Red-Light metrics
- [x] Red-Light intercept (<500 ms)
- [x] RAG chunking + embedding (~13.5k vectors, sentence-transformers)
- [x] CLI + FastAPI query endpoint
- [x] Bilingual answers + SQLite history
- [x] OpenAI GREEN/YELLOW answers (optional `.env`)
- [x] Pytest suite
- [x] Fixed triage eval suite (`evals/cases.json`)
- [x] Expanded owner clinical corpus (urinary / heart / neuro / immune / …)
- [x] Web demo UX + DEMO_GUIDE smoke (`scripts/smoke_demo_guide.sh`)
- [x] AnimaLink merge handoff doc (`docs/MERGE_TO_ANIMALINK.md`)

Out of scope for this lab repo (belongs in AnimaLink product):

- [ ] Wire triage API into AnimaLink UI / Edge Functions
- [ ] Module B/C corpus ingest into AnimaLink pgvector
- [ ] Production HTTPS / TestFlight
## License & disclaimer

Merck Veterinary Manual content is © Merck & Co., Inc. This lab pipeline is for research/education. **Not a substitute for professional veterinary care.** Always escalate emergencies to a licensed veterinarian.
