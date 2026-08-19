"""FastAPI server exposing the ANIMA emergency triage RAG pipeline.

App integration contract: POST /v1/triage/query
Legacy aliases kept for the local demo UI: POST /triage/query
"""

from __future__ import annotations

import importlib.util
import json
import logging
import os
import secrets
import sys
import uuid
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPTS_DIR)
FRONTEND_DIR = os.path.join(PROJECT_ROOT, "frontend")

API_VERSION = "v1"
SERVICE_NAME = "ANIMA-RAG-Lab Triage API"


def _load_dotenv(path: Optional[str] = None) -> None:
    env_path = path or os.path.join(PROJECT_ROOT, ".env")
    if not os.path.isfile(env_path):
        return
    try:
        with open(env_path, encoding="utf-8") as env_file:
            for raw in env_file:
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip("'").strip('"')
                if key and key not in os.environ:
                    os.environ[key] = value
    except OSError as exc:
        logger.warning("Could not read .env: %s", exc)


_load_dotenv()


def _load_pipeline_module():
    path = os.path.join(SCRIPTS_DIR, "06_rag_query.py")
    spec = importlib.util.spec_from_file_location("anima_rag_query", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load pipeline from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["anima_rag_query"] = module
    spec.loader.exec_module(module)
    return module


def _load_cbarq_module():
    path = os.path.join(SCRIPTS_DIR, "19_cbarq_personality.py")
    spec = importlib.util.spec_from_file_location("anima_cbarq_personality", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load C-BARQ scorer from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["anima_cbarq_personality"] = module
    spec.loader.exec_module(module)
    return module


def _load_mcpq_module():
    path = os.path.join(SCRIPTS_DIR, "20_mcpq_personality.py")
    spec = importlib.util.spec_from_file_location("anima_mcpq_personality", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load MCPQ-R scorer from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["anima_mcpq_personality"] = module
    spec.loader.exec_module(module)
    return module


def _load_store_module():
    path = os.path.join(SCRIPTS_DIR, "08_triage_store.py")
    spec = importlib.util.spec_from_file_location("anima_triage_store", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load store from {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["anima_triage_store"] = module
    spec.loader.exec_module(module)
    return module


_pipeline_mod = _load_pipeline_module()
_store_mod = _load_store_module()
_cbarq_mod = _load_cbarq_module()
_mcpq_mod = _load_mcpq_module()
AnimaRAGPipeline = _pipeline_mod.AnimaRAGPipeline
RAGQueryRequest = _pipeline_mod.RAGQueryRequest
TriageResultStore = _store_mod.TriageResultStore
CBarqPersonality = _cbarq_mod.CBarqPersonality
MCPQRPersonality = _mcpq_mod.MCPQRPersonality

_pipeline: Optional[AnimaRAGPipeline] = None
_store: Optional[TriageResultStore] = None
_cache = None
_cbarq: Optional[CBarqPersonality] = None
_mcpq: Optional[MCPQRPersonality] = None


def _configured_api_key() -> str:
    return (os.getenv("ANIMA_API_KEY") or "").strip()


def _cors_origins() -> List[str]:
    raw = (os.getenv("ANIMA_CORS_ORIGINS") or "").strip()
    if raw:
        return [part.strip() for part in raw.split(",") if part.strip()]
    return [
        "http://127.0.0.1:8000",
        "http://localhost:8000",
        "http://127.0.0.1:5500",
        "http://localhost:5500",
        "null",
    ]


def _error_body(
    code: str,
    message: str,
    *,
    request_id: Optional[str] = None,
    details: Any = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }
    if details is not None:
        payload["error"]["details"] = details
    return payload


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _pipeline, _store, _cache, _cbarq, _mcpq
    logger.info("Starting ANIMA triage API — loading vector store and Red-Light index")
    _pipeline = AnimaRAGPipeline()
    _pipeline.vector_store.load()
    _store = TriageResultStore()
    _cbarq = CBarqPersonality()
    _mcpq = MCPQRPersonality()
    try:
        from semantic_cache import SemanticCache

        _cache = SemanticCache()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Semantic cache init skipped: %s", exc)
        _cache = None
    auth_mode = "required" if _configured_api_key() else "open (dev)"
    retrieval = getattr(_pipeline.vector_store, "active_backend", lambda: "?")()
    logger.info(
        "Pipeline ready; triage DB: %s; LLM: %s; auth: %s; store: %s; retrieval: %s; cache: %s",
        _store.db_path,
        (
            f"on ({_pipeline.openai_model})"
            if _pipeline.llm_enabled
            else "off (extractive fallback)"
        ),
        auth_mode,
        getattr(_pipeline.vector_store, "store_dir", "?"),
        retrieval,
        (
            f"on ({getattr(_cache, 'backend', '?')})"
            if getattr(_cache, "enabled", False)
            else "off"
        ),
    )
    yield
    logger.info("Shutting down ANIMA triage API")


app = FastAPI(
    title=SERVICE_NAME,
    description=(
        "Emergency veterinary triage with Red-Light intercept and Merck RAG retrieval.\n\n"
        "**App contract:** `POST /v1/triage/query`\n\n"
        "When `ANIMA_API_KEY` is set, send `X-API-Key: <key>` or "
        "`Authorization: Bearer <key>`.\n\n"
        "See `docs/APP_INTEGRATION.md` for field tables and client examples."
    ),
    version="0.2.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TriageQueryRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="Owner/clinician free-text situation description",
        examples=["中暑怎么办？散步后喘气、流口水，仍清醒能走。"],
    )
    species: Optional[str] = Field(
        None,
        description="dog | cat | unknown",
        examples=["dog"],
    )
    size: Optional[str] = Field(
        None,
        description="small | large (dogs only)",
        examples=["small"],
    )
    heart_rate_bpm: Optional[float] = Field(None, ge=0, le=400)
    crt_seconds: Optional[float] = Field(None, ge=0, le=10)
    rectal_temp_f: Optional[float] = Field(None, ge=85, le=115)
    rectal_temp_c: Optional[float] = Field(None, ge=29, le=46)
    map_mmhg: Optional[float] = Field(None, ge=0, le=300)
    symptoms: List[str] = Field(
        default_factory=list,
        description="Optional override; normally extracted from question text",
    )
    chief_complaint: str = Field(
        default="",
        max_length=4000,
        description="Deprecated alias — prefer putting all free text in question",
    )
    top_k: int = Field(default=5, ge=1, le=20)
    client_request_id: Optional[str] = Field(
        None,
        max_length=128,
        description="Optional idempotency / tracing id from the App",
    )


class SourceItem(BaseModel):
    rank: Optional[int] = None
    score: Optional[float] = None
    chunk_id: Optional[str] = None
    content: Optional[str] = None
    content_zh: Optional[str] = None
    chunk_type_zh: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class TriageQueryResponse(BaseModel):
    api_version: str = API_VERSION
    request_id: str
    record_id: Optional[str] = None
    answer: str
    answer_zh: str
    answer_en: str
    recommendation_zh: str = ""
    recommendation_en: str = ""
    intercepted: bool
    red_light_status: Optional[str] = Field(
        None, description="RED | YELLOW | GREEN"
    )
    red_light: Optional[Dict[str, Any]] = None
    sources: List[Dict[str, Any]] = Field(default_factory=list)
    retrieval_query: str = ""
    model_used: str = ""
    elapsed_ms: float = 0.0
    evaluated_at: str = ""
    extracted_symptoms: List[str] = Field(default_factory=list)
    cache_hit: bool = False


class HealthResponse(BaseModel):
    status: str
    api_version: str = API_VERSION
    auth_required: bool = False
    vector_store_loaded: bool
    embedder: Optional[str]
    vector_count: Optional[int]
    llm_enabled: bool = False
    llm_model: Optional[str] = None
    toxic_plants_loaded: bool = False
    complaint_map_loaded: bool = False
    cache_enabled: bool = False
    cache_backend: Optional[str] = None
    retrieval: Optional[str] = None
    cbarq_personality_loaded: bool = False
    mcpq_personality_loaded: bool = False


class CBarqScoreRequest(BaseModel):
    answers: Dict[str, float] = Field(
        ...,
        description="C-BARQ42 item number → 0–4. Keys: '1' or 'item_1'.",
    )


class MCPQScoreRequest(BaseModel):
    answers: Dict[str, float] = Field(
        ...,
        description="MCPQ-R item number → 1–6. Keys: '1' or 'item_1'.",
    )


class ResultsListResponse(BaseModel):
    api_version: str = API_VERSION
    count: int
    results: List[Dict[str, Any]]


async def require_api_key(
    request: Request,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
    authorization: Optional[str] = Header(default=None),
) -> None:
    """Enforce API key when ANIMA_API_KEY is configured."""
    expected = _configured_api_key()
    if not expected:
        return

    provided = (x_api_key or "").strip()
    if not provided and authorization:
        auth = authorization.strip()
        if auth.lower().startswith("bearer "):
            provided = auth[7:].strip()
        else:
            provided = auth

    request_id = getattr(request.state, "request_id", None)
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=401,
            detail=_error_body(
                "unauthorized",
                "Missing or invalid API key. Send X-API-Key or Authorization: Bearer.",
                request_id=request_id,
            ),
        )


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    response.headers["X-API-Version"] = API_VERSION
    return response


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = getattr(request.state, "request_id", None)
    if isinstance(exc.detail, dict) and "error" in exc.detail:
        body = exc.detail
        if request_id and not body["error"].get("request_id"):
            body["error"]["request_id"] = request_id
        return JSONResponse(status_code=exc.status_code, content=body)

    code_map = {
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        422: "validation_error",
        503: "service_unavailable",
    }
    code = code_map.get(exc.status_code, "http_error")
    return JSONResponse(
        status_code=exc.status_code,
        content=_error_body(code, str(exc.detail), request_id=request_id),
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    request_id = getattr(request.state, "request_id", None)
    return JSONResponse(
        status_code=422,
        content=_error_body(
            "validation_error",
            "Request validation failed",
            request_id=request_id,
            details=exc.errors(),
        ),
    )


def _run_triage(
    body: TriageQueryRequest,
    request: Request,
) -> Dict[str, Any]:
    if _pipeline is None or _store is None:
        raise HTTPException(
            status_code=503,
            detail=_error_body(
                "service_unavailable",
                "Pipeline not initialized",
                request_id=getattr(request.state, "request_id", None),
            ),
        )

    request_id = body.client_request_id or getattr(
        request.state, "request_id", str(uuid.uuid4())
    )
    try:
        request_payload = body.model_dump(exclude={"client_request_id"})
        species = str(request_payload.get("species") or "")
        question = str(request_payload.get("question") or "")
        if _cache is not None and getattr(_cache, "enabled", False):
            cached = _cache.get(question, species)
            if cached and not cached.get("intercepted"):
                cached = dict(cached)
                cached["api_version"] = API_VERSION
                cached["request_id"] = request_id
                cached["cache_hit"] = True
                return cached

        rag_request = RAGQueryRequest(**request_payload)
        result = _pipeline.query(rag_request)
        payload = result.to_dict()
        record_id = _store.save(request=request_payload, response=payload)
        payload["record_id"] = record_id
        payload["api_version"] = API_VERSION
        payload["request_id"] = request_id
        if (
            _cache is not None
            and getattr(_cache, "enabled", False)
            and not payload.get("intercepted")
        ):
            _cache.set(question, payload, species)
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Triage query failed request_id=%s", request_id)
        raise HTTPException(
            status_code=500,
            detail=_error_body(
                "internal_error",
                "Triage pipeline failed",
                request_id=request_id,
                details=str(exc),
            ),
        ) from exc


@app.get("/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    if _pipeline is None:
        raise HTTPException(status_code=503, detail="Pipeline not initialized")
    store_dir = getattr(_pipeline.vector_store, "store_dir", None) or os.path.join(
        PROJECT_ROOT, "data", "processed", "merck_vector_store"
    )
    manifest_path = os.path.join(store_dir, "manifest.json")
    embedder = None
    vector_count = None
    if os.path.exists(manifest_path):
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        embedder = manifest.get("embedder")
        vector_count = manifest.get("vector_count")

    toxic_path = os.path.join(
        PROJECT_ROOT, "data", "triage_tree", "aspca_toxic_plants.json"
    )
    complaint_path = os.path.join(
        PROJECT_ROOT, "data", "triage_tree", "complaint_clinical_map.json"
    )
    retrieval = None
    store = _pipeline.vector_store
    if hasattr(store, "active_backend"):
        retrieval = store.active_backend()
    loaded = store.embedder is not None and (
        store.vectors is not None or retrieval == "supabase"
    )
    return HealthResponse(
        status="ok",
        api_version=API_VERSION,
        auth_required=bool(_configured_api_key()),
        vector_store_loaded=loaded,
        embedder=embedder,
        vector_count=vector_count,
        llm_enabled=bool(getattr(_pipeline, "llm_enabled", False)),
        llm_model=(
            getattr(_pipeline, "openai_model", None)
            if getattr(_pipeline, "llm_enabled", False)
            else None
        ),
        toxic_plants_loaded=os.path.isfile(toxic_path),
        complaint_map_loaded=os.path.isfile(complaint_path),
        cache_enabled=bool(getattr(_cache, "enabled", False)),
        cache_backend=getattr(_cache, "backend", None) if _cache else "off",
        retrieval=retrieval,
        cbarq_personality_loaded=_cbarq is not None,
        mcpq_personality_loaded=_mcpq is not None,
    )


@app.get("/api", tags=["system"])
@app.get(f"/{API_VERSION}", tags=["system"])
def api_info() -> Dict[str, Any]:
    return {
        "service": SERVICE_NAME,
        "api_version": API_VERSION,
        "auth_required": bool(_configured_api_key()),
        "frontend": "/",
        "docs": "/docs",
        "openapi": "/openapi.json",
        "health": "GET /health",
        "query_endpoint": f"POST /{API_VERSION}/triage/query",
        "results_endpoint": f"GET /{API_VERSION}/triage/results",
        "personality_cbarq_form": f"GET /{API_VERSION}/personality/cbarq",
        "personality_cbarq_score": f"POST /{API_VERSION}/personality/cbarq/score",
        "personality_mcpq_form": f"GET /{API_VERSION}/personality/mcpq",
        "personality_mcpq_score": f"POST /{API_VERSION}/personality/mcpq/score",
        "legacy_query_endpoint": "POST /triage/query",
        "integration_guide": "docs/APP_INTEGRATION.md",
    }


@app.get(
    f"/{API_VERSION}/personality/cbarq",
    tags=["personality"],
    dependencies=[Depends(require_api_key)],
    summary="C-BARQ42 form spec (item numbers only; no copyrighted stems)",
)
def personality_cbarq_form() -> Dict[str, Any]:
    if _cbarq is None:
        raise HTTPException(status_code=503, detail="C-BARQ scorer not initialized")
    return {"api_version": API_VERSION, **_cbarq.form_spec()}


@app.post(
    f"/{API_VERSION}/personality/cbarq/score",
    tags=["personality"],
    dependencies=[Depends(require_api_key)],
    summary="Score C-BARQ42 answers → personality + care needs",
)
def personality_cbarq_score(body: CBarqScoreRequest) -> Dict[str, Any]:
    if _cbarq is None:
        raise HTTPException(status_code=503, detail="C-BARQ scorer not initialized")
    try:
        report = _cbarq.score(body.answers)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=_error_body("validation_error", str(exc)),
        ) from exc
    return {"api_version": API_VERSION, **report}


@app.get(
    f"/{API_VERSION}/personality/mcpq",
    tags=["personality"],
    dependencies=[Depends(require_api_key)],
    summary="MCPQ-R form spec (26 adjectives; Lab-derived blank form)",
)
def personality_mcpq_form() -> Dict[str, Any]:
    if _mcpq is None:
        raise HTTPException(status_code=503, detail="MCPQ-R scorer not initialized")
    return {"api_version": API_VERSION, **_mcpq.form_spec()}


@app.post(
    f"/{API_VERSION}/personality/mcpq/score",
    tags=["personality"],
    dependencies=[Depends(require_api_key)],
    summary="Score MCPQ-R answers → personality + care needs",
)
def personality_mcpq_score(body: MCPQScoreRequest) -> Dict[str, Any]:
    if _mcpq is None:
        raise HTTPException(status_code=503, detail="MCPQ-R scorer not initialized")
    try:
        report = _mcpq.score(body.answers)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=_error_body("validation_error", str(exc)),
        ) from exc
    return {"api_version": API_VERSION, **report}


@app.post(
    f"/{API_VERSION}/triage/query",
    response_model=TriageQueryResponse,
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
    summary="Run emergency triage (App contract)",
)
@app.post(
    "/triage/query",
    response_model=TriageQueryResponse,
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
    summary="Legacy alias for /v1/triage/query",
    include_in_schema=True,
)
def triage_query(body: TriageQueryRequest, request: Request) -> Dict[str, Any]:
    return _run_triage(body, request)


@app.get(
    f"/{API_VERSION}/triage/results",
    response_model=ResultsListResponse,
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
)
@app.get(
    "/triage/results",
    response_model=ResultsListResponse,
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
    include_in_schema=False,
)
def list_triage_results(
    limit: int = Query(default=20, ge=1, le=100),
) -> Dict[str, Any]:
    if _store is None:
        raise HTTPException(status_code=503, detail="Store not initialized")
    rows = _store.list_recent(limit=limit)
    return {
        "api_version": API_VERSION,
        "count": len(rows),
        "results": rows,
    }


@app.get(
    f"/{API_VERSION}/triage/results/{{record_id}}",
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
)
@app.get(
    "/triage/results/{record_id}",
    tags=["triage"],
    dependencies=[Depends(require_api_key)],
    include_in_schema=False,
)
def get_triage_result(record_id: str) -> Dict[str, Any]:
    if _store is None:
        raise HTTPException(status_code=503, detail="Store not initialized")
    row = _store.get(record_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Triage result not found")
    row = dict(row)
    row["api_version"] = API_VERSION
    return row


@app.get("/", tags=["system"])
def frontend_home():
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if not os.path.exists(index_path):
        return api_info()
    return FileResponse(index_path)


if os.path.isdir(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    host = os.getenv("ANIMA_API_HOST", "127.0.0.1")
    port = int(os.getenv("ANIMA_API_PORT", "8000"))
    uvicorn.run(app, host=host, port=port, reload=False)
