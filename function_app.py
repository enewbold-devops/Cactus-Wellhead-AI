import os
import sys
import base64
import json
import logging
import uuid
from datetime import datetime, timezone

if "__main__" not in sys.modules: 
    import types
    sys.modules["__main__"] = types.ModuleType("__main__")

import transformers
transformers.logging.set_verbosity_error()


class _HFTokenWarningFilter(logging.Filter):
    """Suppress noisy HuggingFace tokenizer sequence-length warnings emitted by Docling."""
    def filter(self, record: logging.LogRecord) -> bool:
        return "Token indices sequence length" not in record.getMessage()


_hf_warning_filter = _HFTokenWarningFilter()
logging.getLogger().addFilter(_hf_warning_filter)
logging.getLogger("transformers").addFilter(_hf_warning_filter)


from azure.core.exceptions import AzureError
from py_azurite_blob_storage import CactusWHDBlobStorage
from py_azurite_queue_storage import AzuriteQueueManager

import azure.functions as func

MTR_INTAKE_QUEUE    = "mtr-intake-queue"
MTR_VECTORIZE_QUEUE = "mtr-vectorize-queue"

_store = CactusWHDBlobStorage()
_queue = AzuriteQueueManager()

app = func.FunctionApp(http_auth_level=func.AuthLevel.ANONYMOUS)


# ------------------------------------------------------------------
# Helper
# ------------------------------------------------------------------

def _json_response(data, status_code: int = 200) -> func.HttpResponse:
    """Serialise data to a JSON HttpResponse with the correct content-type header."""
    return func.HttpResponse(
        body=json.dumps(data, ensure_ascii=False),
        status_code=status_code,
        mimetype="application/json",
    )


def _error_response(message: str, status_code: int = 500) -> func.HttpResponse:
    return _json_response({"error": message}, status_code=status_code)


def _safe_json_parse(raw: str | None, default=None):
    """Silently parse a JSON string; return default on failure."""
    if not raw:
        return default if default is not None else {}
    try:
        return json.loads(raw)
    except Exception:
        return default if default is not None else {}


# ------------------------------------------------------------------
# Route 1 — GET /api/cms/providers
# Returns the full approved-providers list as a JSON array.
# ------------------------------------------------------------------

@app.route(route="cms/providers", methods=["GET"])
def http_cms_providers(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("[cms/providers] request received")
    try:
        data = _store.get_approved_providers()
        return _json_response(data)
    except AzureError as exc:
        logging.exception("[cms/providers] blob storage error")
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[cms/providers] unexpected error")
        return _error_response(f"Unexpected error: {exc}", 500)


# ------------------------------------------------------------------
# Route 2 — GET /api/cms/crosswalk
# Returns the CMS-to-process-code crosswalk as a JSON array.
# ------------------------------------------------------------------

@app.route(route="cms/crosswalk", methods=["GET"])
def http_cms_crosswalk(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("[cms/crosswalk] request received")
    try:
        data = _store.get_cms_process_crosswalk()
        return _json_response(data)
    except AzureError as exc:
        logging.exception("[cms/crosswalk] blob storage error")
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[cms/crosswalk] unexpected error")
        return _error_response(f"Unexpected error: {exc}", 500)


# ------------------------------------------------------------------
# Route 3 — GET /api/cms/chunks?cms_number=CMS-002
# Returns all JSONL chunk records whose doc.cms_number matches the
# cms_number query-string parameter.  Returns 400 when the param
# is missing, 200 with [] when no matching chunks are found.
# ------------------------------------------------------------------

@app.route(route="cms/chunks", methods=["GET"])
def http_cms_chunks(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("[cms/chunks] request received")

    cms_number = req.params.get("cms_number", "").strip()
    if not cms_number:
        return _error_response(
            "Missing required query parameter: cms_number (e.g. ?cms_number=CMS-002)",
            status_code=400,
        )

    try:
        data = _store.get_cms_chunks(cms_number)
        logging.info("[cms/chunks] %s → %d chunks returned", cms_number, len(data))
        return _json_response(data)
    except AzureError as exc:
        logging.exception("[cms/chunks] blob storage error")
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[cms/chunks] unexpected error")
        return _error_response(f"Unexpected error: {exc}", 500)


# ------------------------------------------------------------------
# Route 4 — POST /api/mtr/intake
# Accepts a raw file upload (multipart/form-data, field name "file").
# Stores the original file to cactus-mtr, writes an initial status
# record, enqueues a processing message, and returns the case_id.
# ------------------------------------------------------------------

_ALLOWED_EXTENSIONS: set[str] = {".pdf", ".docx", ".xlsx", ".jpg", ".jpeg", ".png", ".tif", ".tiff"}
_SUFFIX_MAP: dict[str, str] = {".jpeg": ".jpg", ".tiff": ".tif"}


@app.route(route="mtr/intake", methods=["POST"])
def http_mtr_intake(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("[mtr/intake] request received")

    # NOTE: PDFProcessor (torch/docling) must NEVER be imported here.
    # dill (a torch dependency) calls `import __main__` which does not
    # exist in the Azure Functions HTTP worker process. PDFProcessor is
    # imported only inside mtr_intake_processor (queue trigger).

    # ── 1. Extract file from multipart form ──────────────────────────────
    uploaded = req.files.get("file")
    if not uploaded:
        return _error_response(
            "Missing required form field: 'file'. Send a multipart/form-data POST "
            "with the MTR document in a field named 'file'.",
            status_code=400,
        )

    filename: str = uploaded.filename or "upload.pdf"
    file_bytes: bytes = uploaded.read()

    if not file_bytes:
        return _error_response("Uploaded file is empty.", status_code=400)

    # ── 2. Validate extension ────────────────────────────────────────────
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in _ALLOWED_EXTENSIONS:
        return _error_response(
            f"Unsupported file type '{ext}'. "
            f"Allowed: {', '.join(sorted(_ALLOWED_EXTENSIONS))}",
            status_code=415,
        )

    # Normalise suffix (.jpeg → .jpg, .tiff → .tif) — no PDFProcessor needed
    suffix = _SUFFIX_MAP.get(ext, ext)

    # ── 3. Create case record ────────────────────────────────────────────
    case_id = str(uuid.uuid4())
    submitted_at = datetime.now(timezone.utc).isoformat()

    status_record = {
        "case_id": case_id,
        "status": "queued",
        "filename": filename,
        "submitted_at": submitted_at,
        "completed_at": None,
        "artifacts": {
            "raw": f"mtr/{case_id}/raw/{filename}",
            "markdown": f"mtr/{case_id}/processed/{case_id}.md",
            "chunks_jsonl": f"mtr/{case_id}/processed/{case_id}_chunks.jsonl",
            "structured_json": f"mtr/{case_id}/processed/{case_id}_structured.json",
        },
        "error": None,
    }

    # ── 4. Store raw file and initial status ─────────────────────────────
    try:
        result = _store.write_mtr_raw(case_id, file_bytes, filename)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "write_mtr_raw failed"))

        result = _store.write_mtr_status(case_id, status_record)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "write_mtr_status failed"))
    except AzureError as exc:
        logging.exception("[mtr/intake] blob storage error for case %s", case_id)
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[mtr/intake] unexpected error for case %s", case_id)
        return _error_response(f"Unexpected error: {exc}", 500)

    # ── 5. Enqueue processing message ─────────────────────────────────────
    queue_message = json.dumps({
        "case_id": case_id,
        "filename": filename,
        "suffix": suffix,
        "submitted_at": submitted_at,
    }, ensure_ascii=False)

    try:
        # host.json has messageEncoding=base64 — the Functions queue trigger
        # will base64-decode before passing to mtr_intake_processor, so we
        # must base64-encode when sending.
        encoded_message = base64.b64encode(queue_message.encode("utf-8")).decode("ascii")
        _queue.send_message(MTR_INTAKE_QUEUE, encoded_message)
        logging.info("[mtr/intake] enqueued case_id=%s filename=%s", case_id, filename)
    except Exception as exc:
        # Degraded mode: still return the case_id but flag the queue failure
        logging.exception("[mtr/intake] queue send failed for case %s", case_id)
        status_record["status"] = "queue_error"
        status_record["error"] = f"File stored but queue send failed: {exc}"
        _store.write_mtr_status(case_id, status_record)
        return _json_response(
            {
                "case_id": case_id,
                "status": "queue_error",
                "warning": "File accepted but could not be enqueued for processing. "
                           "Retry or contact support.",
                "status_url": f"/api/mtr/{case_id}/status",
            },
            status_code=202
        )

    return _json_response(
        {
            "case_id": case_id,
            "status": "queued",
            "filename": filename,
            "submitted_at": submitted_at,
            "status_url": f"/api/mtr/{case_id}/status",
        },
        status_code=201,
    )


# ------------------------------------------------------------------
# Route 5 — GET /api/mtr/{case_id}/status
# Returns the current status record for an MTR case.
# ------------------------------------------------------------------

@app.route(route="mtr/{case_id}/status", methods=["GET"])
def http_mtr_status(req: func.HttpRequest) -> func.HttpResponse:
    case_id: str = req.route_params.get("case_id", "").strip()
    logging.info("[mtr/status] request received case_id=%s", case_id)

    if not case_id:
        return _error_response("Missing route parameter: case_id", status_code=400)

    try:
        record = _store.get_mtr_status(case_id)
    except AzureError as exc:
        logging.exception("[mtr/status] blob storage error case_id=%s", case_id)
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[mtr/status] unexpected error case_id=%s", case_id)
        return _error_response(f"Unexpected error: {exc}", 500)

    if record is None:
        return _error_response(f"Case not found: {case_id}", status_code=404)

    return _json_response(record)


# ------------------------------------------------------------------
# Route 6 — GET /api/mtr/{case_id}/validation
# Returns the full validation.json artifact (gate results, CMS set,
# chunk classifications, providers) written by mtr_vectorize_processor.
# Returns 404 when the case has not yet been vectorized.
# ------------------------------------------------------------------

@app.route(route="mtr/{case_id}/validation", methods=["GET"])
def http_mtr_validation(req: func.HttpRequest) -> func.HttpResponse:
    case_id: str = req.route_params.get("case_id", "").strip()
    logging.info("[mtr/validation] request received case_id=%s", case_id)

    if not case_id:
        return _error_response("Missing route parameter: case_id", status_code=400)

    try:
        record = _store.get_mtr_validation_json(case_id)
    except AzureError as exc:
        logging.exception("[mtr/validation] blob storage error case_id=%s", case_id)
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[mtr/validation] unexpected error case_id=%s", case_id)
        return _error_response(f"Unexpected error: {exc}", 500)

    if record is None:
        return _error_response(
            f"Validation report not yet available for case: {case_id}. "
            "Check /status — case may still be vectorizing.",
            status_code=404,
        )

    return _json_response(record)


# ------------------------------------------------------------------
# Route 7 — POST /api/mtr/{case_id}/evaluate
# Requirement Evaluator: embeds a free-text requirement string, runs a
# hybrid (vector + metadata) query against the per-case LanceDB table,
# and optionally cross-queries the shared CMS spec chunks table.
# Returns structured evidence packets for external agent-side reasoning.
#
# Request body (JSON):
#   requirement_text  str   — the requirement or question to evaluate (required)
#   semantic_classes  list  — restrict MTR hits to these classes (optional)
#   cms_numbers       list  — restrict CMS hits to these specs (optional)
#   top_k             int   — max hits per table, default 8, max 20 (optional)
#   min_score         float — discard hits below this cosine similarity (optional)
#   include_cms       bool  — also query CMS spec table, default true (optional)
# ------------------------------------------------------------------

@app.route(route="mtr/{case_id}/evaluate", methods=["POST"])
def http_mtr_evaluate(req: func.HttpRequest) -> func.HttpResponse:
    case_id: str = req.route_params.get("case_id", "").strip()
    logging.info("[mtr/evaluate] request received case_id=%s", case_id)

    if not case_id:
        return _error_response("Missing route parameter: case_id", status_code=400)

    # ── Parse request body ───────────────────────────────────────────────
    try:
        body: dict = req.get_json()
    except Exception:
        return _error_response("Invalid or missing JSON body.", status_code=400)

    requirement_text: str = (body.get("requirement_text") or "").strip()
    if not requirement_text:
        return _error_response(
            "Missing required field: 'requirement_text' — provide the requirement "
            "or question text to evaluate against the MTR.",
            status_code=400,
        )

    semantic_classes: list[str] | None = body.get("semantic_classes") or None
    cms_numbers: list[str] | None = body.get("cms_numbers") or None
    top_k: int = max(1, min(int(body.get("top_k", 8)), 20))
    min_score: float = float(body.get("min_score", 0.0))
    include_cms: bool = bool(body.get("include_cms", True))

    # ── Lazy imports (keep heavy deps away from cold HTTP path) ──────────
    from openai import AzureOpenAI
    from py_vectodb import LanceDBManager

    # ── Check environment ────────────────────────────────────────────────
    try:
        oai_client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version="2024-02-01",
        )
    except KeyError as exc:
        logging.error("[mtr/evaluate] missing Azure OpenAI env var: %s", exc)
        return _error_response(f"Azure OpenAI configuration missing: {exc}", status_code=503)

    # ── 1. Verify the case vector table exists ───────────────────────────
    mgr = LanceDBManager()
    if not mgr.case_table_exists(case_id):
        return _error_response(
            f"No vector table found for case: {case_id}. "
            "Case may not have completed vectorization — check /api/mtr/{case_id}/status.",
            status_code=404,
        )

    # ── 2. Embed the requirement text ────────────────────────────────────
    EMBED_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")
    try:
        embed_response = oai_client.embeddings.create(
            input=[requirement_text],
            model=EMBED_DEPLOYMENT,
            dimensions=3072,
        )
        query_vector: list[float] = embed_response.data[0].embedding
        logging.info(
            "[mtr/evaluate] embedded requirement text (%d dims) case_id=%s",
            len(query_vector), case_id,
        )
    except Exception as exc:
        logging.exception("[mtr/evaluate] embedding API failed case_id=%s", case_id)
        return _error_response(f"Embedding API error: {exc}", status_code=502)

    queried_at = datetime.now(timezone.utc).isoformat()

    # ── 3. Query per-case MTR vector table ───────────────────────────────
    try:
        mtr_raw = mgr.query_case_chunks_for_eval(
            case_id,
            query_vector,
            semantic_classes=semantic_classes,
            limit=top_k,
            min_score=min_score,
        )
    except Exception as exc:
        logging.exception("[mtr/evaluate] LanceDB case query failed case_id=%s", case_id)
        return _error_response(f"LanceDB query error: {exc}", status_code=500)

    mtr_hits = [
        {
            "chunk_index":      r.get("chunk_index"),
            "semantic_class":   r.get("semantic_class"),
            "confidence":       r.get("confidence"),
            "vector_score":     r.get("vector_score"),
            "page_no":          r.get("page_no"),
            "heading_context":  r.get("heading_context"),
            "text":             r.get("text"),
            "extracted_fields": _safe_json_parse(r.get("extracted_fields"), default={}),
            "provider_name":    r.get("provider_name"),
            "provider_code":    r.get("provider_code"),
            "bbox":             _safe_json_parse(r.get("bbox"), default={}),
        }
        for r in mtr_raw
    ]
    logging.info(
        "[mtr/evaluate] MTR query returned %d hits case_id=%s", len(mtr_hits), case_id
    )

    # ── 4. Query shared CMS spec table (optional) ────────────────────────
    cms_hits: list[dict] = []
    if include_cms:
        try:
            cms_raw = mgr.query_cms_table_for_eval(
                query_vector,
                cms_numbers=cms_numbers,
                limit=top_k,
                min_score=min_score,
            )
            cms_hits = [
                {
                    "id":                r.get("id"),
                    "cms_number":        r.get("cms_number"),
                    "canonical_section": r.get("canonical_section"),
                    "section_path":      _safe_json_parse(r.get("section_path"), default=[]),
                    "text":              r.get("text"),
                    "params":            _safe_json_parse(r.get("params"), default={}),
                    "vector_score":      r.get("vector_score"),
                }
                for r in cms_raw
            ]
            logging.info(
                "[mtr/evaluate] CMS query returned %d hits case_id=%s", len(cms_hits), case_id
            )
        except Exception as exc:
            # CMS table may not be seeded yet — non-fatal
            logging.warning("[mtr/evaluate] CMS query failed (non-fatal): %s", exc)

    # ── 5. Confidence summary ────────────────────────────────────────────
    class_distribution: dict[str, int] = {}
    for hit in mtr_hits:
        cls = hit["semantic_class"] or "other"
        class_distribution[cls] = class_distribution.get(cls, 0) + 1

    cms_sections = list({h["canonical_section"] for h in cms_hits if h.get("canonical_section")})
    top_mtr_score = mtr_hits[0]["vector_score"] if mtr_hits else None
    top_cms_score = cms_hits[0]["vector_score"] if cms_hits else None

    confidence_summary = {
        "mtr_hits_returned":         len(mtr_hits),
        "cms_hits_returned":         len(cms_hits),
        "semantic_class_distribution": class_distribution,
        "top_mtr_vector_score":      top_mtr_score,
        "top_cms_vector_score":      top_cms_score,
        "cms_sections_found":         cms_sections,
        # Flag as ambiguous when best MTR hit is below 0.75 cosine similarity
        "ambiguity_flag":            top_mtr_score is not None and top_mtr_score < 0.75,
    }

    return _json_response(
        {
            "case_id":          case_id,
            "requirement_text": requirement_text,
            "queried_at":       queried_at,
            "filters_applied": {
                "semantic_classes": semantic_classes,
                "cms_numbers":      cms_numbers,
                "top_k":            top_k,
                "min_score":        min_score,
                "include_cms":      include_cms,
            },
            "mtr_hits":          mtr_hits,
            "cms_hits":          cms_hits,
            "confidence_summary": confidence_summary,
        }
    )


# ------------------------------------------------------------------
# Queue trigger — mtr-intake-queue
# Reads the raw MTR file from blob, runs Docling convert+chunk, and
# writes all four processed artifacts back to the cactus-mtr container.
# Updates status.json throughout: processing → complete | failed.
# ------------------------------------------------------------------

@app.queue_trigger(
    arg_name="msg",
    queue_name=MTR_INTAKE_QUEUE,
    connection="AzureWebJobsStorage",
)
def mtr_intake_processor(msg: func.QueueMessage) -> None:
    # ── Parse queue message ──────────────────────────────────────────────
    try:
        payload: dict = msg.get_json()
    except Exception as exc:
        logging.error("[mtr_processor] could not parse queue message: %s", exc)
        return  # Poison message — let Functions move it to the poison queue

    case_id: str = payload.get("case_id", "")
    filename: str = payload.get("filename", "upload.pdf")
    suffix: str = payload.get("suffix", ".pdf")
    logging.info("[mtr_processor] starting case_id=%s filename=%s", case_id, filename)

    def _update_status(updates: dict):
        try:
            current = _store.get_mtr_status(case_id) or {}
            current.update(updates)
            _store.write_mtr_status(case_id, current)
        except Exception as exc_s:
            logging.warning("[mtr_processor] status update failed case_id=%s: %s", case_id, exc_s)

    # ── 1. Mark as processing ────────────────────────────────────────────
    _update_status({"status": "processing"})

    # ── 2. Read raw file from blob ───────────────────────────────────────
    try:
        file_bytes = _store.read_mtr_raw(case_id, filename)
    except Exception as exc:
        logging.exception("[mtr_processor] read_mtr_raw failed case_id=%s", case_id)
        _update_status({"status": "failed", "error": f"Could not read raw file: {exc}"})
        return

    # ── 3. Run Docling (single-pass) ──────────────────────────────────────
    try:
        from py_docling_chunks import PDFProcessor
        _processor = PDFProcessor()

        logging.info("[mtr_processor] running Docling on case_id=%s suffix=%s", case_id, suffix)
        document, raw_chunks = _processor.process_from_bytes(file_bytes, suffix=suffix)
        markdown: str = document.export_to_markdown()

        # Build structured output from the already-converted document
        # (avoids calling process_to_structured which re-processes the file)
        try:
            page_count = len(document.pages) if hasattr(document, "pages") else 0
        except Exception:
            page_count = 0

        chunks_list: list[dict] = []
        for idx, chunk in enumerate(raw_chunks):
            text = chunk.text if hasattr(chunk, "text") else ""
            meta: dict = {}
            if hasattr(chunk, "meta") and chunk.meta is not None:
                try:
                    raw_meta = chunk.meta
                    if hasattr(raw_meta, "model_dump"):
                        meta = {
                            k: v for k, v in raw_meta.model_dump().items()
                            if isinstance(v, (str, int, float, bool, list, dict, type(None)))
                        }
                    elif hasattr(raw_meta, "__dict__"):
                        meta = {
                            k: v for k, v in raw_meta.__dict__.items()
                            if isinstance(v, (str, int, float, bool, list, dict, type(None)))
                        }
                except Exception:
                    meta = {}
            chunks_list.append({"chunk_index": idx, "text": text, "meta": meta})

        structured: dict = {
            "case_id": case_id,
            "filename": filename,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "doc_metadata": {
                "page_count": page_count,
                "source_file": filename,
            },
            "chunks": chunks_list,
        }
    except Exception as exc:
        logging.exception("[mtr_processor] Docling processing failed case_id=%s", case_id)
        _update_status({"status": "failed", "error": f"Document processing error: {exc}"})
        return

    # ── 4. Write artifacts ───────────────────────────────────────────────
    artifact_errors: list[str] = []

    for label, write_fn, args in [
        ("markdown",       _store.write_mtr_markdown,      (case_id, markdown)),
        ("chunks_jsonl",   _store.write_mtr_chunks_jsonl,  (case_id, chunks_list)),
        ("structured_json",_store.write_mtr_structured_json,(case_id, structured)),
    ]:
        try:
            result = write_fn(*args)
            if not result.get("success"):
                artifact_errors.append(f"{label}: {result.get('error', 'unknown')}")
        except Exception as exc:
            artifact_errors.append(f"{label}: {exc}")

    completed_at = datetime.now(timezone.utc).isoformat()

    if artifact_errors:
        logging.error("[mtr_processor] artifact write errors case_id=%s: %s", case_id, artifact_errors)
        _update_status({
            "status": "failed",
            "completed_at": completed_at,
            "error": f"Artifact write failed: {'; '.join(artifact_errors)}",
        })
        return

    # ── 5. Mark complete ─────────────────────────────────────────────────
    _update_status({
        "status": "complete",
        "completed_at": completed_at,
        "chunk_count": len(chunks_list),
        "error": None,
    })
    logging.info(
        "[mtr_processor] complete case_id=%s chunks=%d", case_id, len(chunks_list)
    )
    # ── 6. Enqueue vectorization ──────────────────────────────────────
    vectorize_message = json.dumps({
        "case_id": case_id,
        "filename": filename,
        "chunk_count": len(chunks_list),
        "submitted_at": payload.get("submitted_at", ""),
    }, ensure_ascii=False)
    try:
        encoded_vectorize = base64.b64encode(vectorize_message.encode("utf-8")).decode("ascii")
        _queue.send_message(MTR_VECTORIZE_QUEUE, encoded_vectorize)
        logging.info("[mtr_processor] enqueued vectorize for case_id=%s", case_id)
    except Exception as exc:
        # Non-fatal: Docling processing was successful; log and continue.
        logging.warning(
            "[mtr_processor] vectorize queue send failed for case_id=%s: %s — "
            "vectorization can be re-triggered manually.", case_id, exc
        )


# ------------------------------------------------------------------
# Queue trigger — mtr-vectorize-queue
# Reads the structured JSON artifact produced by mtr_intake_processor,
# classifies and extracts fields from each chunk, embeds them via
# Azure OpenAI text-embedding-3-large (3072 dims), writes a per-case
# LanceDB table, runs Gate 0 + Gate 1 auto-checks, writes a
# validation.json artifact to blob, and updates status.json.
#
# Status transitions:
#   complete → vectorizing → validation_ready | under_review | vectorize_failed
# ------------------------------------------------------------------

@app.queue_trigger(
    arg_name="msg",
    queue_name=MTR_VECTORIZE_QUEUE,
    connection="AzureWebJobsStorage",
)
def mtr_vectorize_processor(msg: func.QueueMessage) -> None:
    # ── Parse queue message ──────────────────────────────────────────────
    try:
        payload: dict = msg.get_json()
    except Exception as exc:
        logging.error("[mtr_vectorize] could not parse queue message: %s", exc)
        return

    case_id: str = payload.get("case_id", "")
    filename: str = payload.get("filename", "")
    logging.info("[mtr_vectorize] starting case_id=%s", case_id)

    # Lazy import: keeps vectorization deps away from Docling/torch worker path
    import re
    import os
    from datetime import datetime, timezone
    from openai import AzureOpenAI
    from py_vectodb import LanceDBManager

    def _update_status(updates: dict):
        try:
            current = _store.get_mtr_status(case_id) or {}
            current.update(updates)
            _store.write_mtr_status(case_id, current)
        except Exception as exc_s:
            logging.warning("[mtr_vectorize] status update failed case_id=%s: %s", case_id, exc_s)

    # ── 1. Mark as vectorizing ───────────────────────────────────────────
    _update_status({"status": "vectorizing"})

    # ── 2. Load structured JSON from blob ───────────────────────────────
    try:
        structured = _store.read_mtr_structured_json(case_id)
        raw_chunks: list[dict] = structured.get("chunks", [])
    except Exception as exc:
        logging.exception("[mtr_vectorize] could not read structured JSON case_id=%s", case_id)
        _update_status({"status": "vectorize_failed", "error": f"Could not load structured JSON: {exc}"})
        return

    if not raw_chunks:
        _update_status({"status": "vectorize_failed", "error": "No chunks found in structured JSON"})
        return

    # ── 3. CMS resolution — scan all chunks for spec references ─────────
    _CMS_PATTERN = re.compile(r"\b(CMS-\d{3}|CNT-\d{3}|CIR-\d{3}|CHT-\w+)\b")
    resolved_cms_set: list[str] = []
    for chunk in raw_chunks:
        for match in _CMS_PATTERN.findall(chunk.get("text", "")):
            if match not in resolved_cms_set:
                resolved_cms_set.append(match)
    logging.info("[mtr_vectorize] resolved CMS set: %s", resolved_cms_set)

    # ── 4. Classify + extract each chunk ────────────────────────────────
    def _classify_chunk(chunk: dict) -> tuple[str, dict, float, bool]:
        """
        Returns (semantic_class, extracted_fields, confidence, needs_review).
        Uses heading context keywords, Docling label, and text pattern signals.
        """
        text: str = chunk.get("text", "")
        text_lower = text.lower()

        meta: dict = chunk.get("meta", {})
        # Docling label — may be nested under meta.doc_items or directly
        label: str = ""
        heading_context: str = ""
        try:
            doc_items = meta.get("doc_items", [])
            if doc_items:
                label = doc_items[0].get("label", "")
                # Walk parent headings for context
                prov = doc_items[0].get("prov", [{}])
                heading_context = meta.get("headings", [""])[0] if meta.get("headings") else ""
        except Exception:
            pass

        # Pattern signals (ordered by specificity)
        _ELEM_SYMBOLS = re.compile(
            r"\b(Carbon|Manganese|Phosphorus|Sulfur|Silicon|Chromium|Molybdenum|Nickel|Vanadium|"
            r"Copper|Niobium|Columbium|Aluminum|Boron|Tin|Lead|Arsenic|Antimony|"
            r"\bC\b|\bMn\b|\bP\b|\bS\b|\bSi\b|\bCr\b|\bMo\b|\bNi\b|\bV\b|\bCu\b)\s*[\(%=:]",
            re.IGNORECASE
        )
        _CHARPY = re.compile(r"charpy|cvn|ft[\-\s]?lb|joule|impact", re.IGNORECASE)
        _HARDNESS = re.compile(r"\bHBW\b|\bHRC\b|\bHRB\b|\bHVN\b|\bhardness\b", re.IGNORECASE)
        _MECHANICAL = re.compile(r"\b(UTS|tensile|yield|elongation|reduction|RA%|PSI|ksi|MPa)\b", re.IGNORECASE)
        _HEAT_TREAT = re.compile(r"austenitiz|normaliz|temper|anneal|quench|solution\s+treat|age|soak|furnace|batch|Q&T", re.IGNORECASE)
        _IDENTITY = re.compile(r"heat\s*(number|no|#)|PO\s*(number|no|#)|lot\s*(number|no|#)|part\s*(number|no|#)|traceability|certificate\s*of\s*(conformance|compliance)", re.IGNORECASE)
        _NDT = re.compile(r"\bUT\b|ultrasonic|magnetic\s+particle|liquid\s+penetrant|radiograph|CNT-|NDE|NDT", re.IGNORECASE)

        extracted: dict = {}
        confidence = 0.85
        needs_review = False

        if _CHARPY.search(text):
            semantic_class = "charpy"
            # Extract temperature and energy values
            temps = re.findall(r"(-?\d+)\s*°?\s*[FC]", text)
            energies = re.findall(r"(\d+\.?\d*)\s*(?:ft[\-\s]?lb|J\b)", text, re.IGNORECASE)
            if temps:
                extracted["test_temp"] = temps[0]
            if energies:
                extracted["energy_values"] = [float(e) for e in energies]

        elif _ELEM_SYMBOLS.search(text) and ("%" in text or "wt" in text_lower):
            semantic_class = "chemistry"
            # Extract element-value pairs
            pairs = re.findall(r"([A-Za-z]{1,3})\s*[\(%=:]\s*(\d+\.?\d*)", text)
            for elem, val in pairs:
                extracted[elem.strip()] = float(val)

        elif _HARDNESS.search(text):
            semantic_class = "hardness"
            vals = re.findall(r"(\d+\.?\d*)\s*(?:HBW|HRC|HRB|HVN)", text, re.IGNORECASE)
            if vals:
                extracted["hardness_values"] = [float(v) for v in vals]

        elif _MECHANICAL.search(text):
            semantic_class = "mechanical"
            psi_vals = re.findall(r"(\d[\d,]*)\s*(?:PSI|psi|ksi|MPa)", text)
            extracted["mechanical_values"] = psi_vals
            pct = re.findall(r"(\d+\.?\d*)\s*%", text)
            if pct:
                extracted["pct_values"] = pct

        elif _HEAT_TREAT.search(text):
            semantic_class = "heat_treatment"
            temps = re.findall(r"(\d{3,4})\s*°?\s*[FC]", text)
            if temps:
                extracted["temperatures"] = temps
            processes = re.findall(
                r"(NORMALIZED|HARDENED|TEMPERED|ANNEALED|QUENCHED|SOLUTION TREATED|AGED)",
                text, re.IGNORECASE
            )
            if processes:
                extracted["processes"] = processes

        elif _NDT.search(text):
            semantic_class = "ndt"

        elif _IDENTITY.search(text):
            semantic_class = "identity"
            heat = re.findall(r"(?:heat\s*(?:number|no|#)\s*[:=]?\s*)([A-Z0-9\-]+)", text, re.IGNORECASE)
            po = re.findall(r"(?:P\.?O\.?\s*(?:number|no|#)?\s*[:=]?\s*)([A-Z0-9\-]+)", text, re.IGNORECASE)
            if heat:
                extracted["heat_number"] = heat[0]
            if po:
                extracted["po_number"] = po[0]
            grade = re.findall(r"\b(4140|4340|17-4\s*PH|17-4PH|718|Alloy 718|316|410)\b", text)
            if grade:
                extracted["grade"] = grade[0]

        else:
            semantic_class = "other"
            needs_review = True
            confidence = 0.50

        return semantic_class, extracted, confidence, needs_review

    def _extract_heading_and_provider(chunk: dict) -> tuple[str, str, str, str]:
        """Extract heading_context, provider_name, provider_city, provider_code from chunk meta."""
        meta: dict = chunk.get("meta", {})
        heading_context = ""
        provider_name = "" 
        provider_city = ""
        provider_code = ""
        try:
            headings = meta.get("headings", [])
            if headings:
                heading_context = headings[0]
        except Exception:
            pass
        text = chunk.get("text", "")
        # Provider code pattern e.g. LAB-001, CNT-005
        codes = re.findall(r"\b(LAB-\d{3}|CNT-\d{3}|HT-\d{3}|UT-\d{3})\b", text)
        if codes:
            provider_code = codes[0]
        # ISO 17025 accredited labs often print their name prominently
        lab_match = re.search(r"([A-Z][A-Za-z\s&,\.]+(?:Labs?|Testing|Inspection|Services|Analytics|Metallurgical))", text)
        if lab_match:
            provider_name = lab_match.group(1).strip()
        # City-state pattern
        city_match = re.search(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)?),\s*[A-Z]{2}\b", text)
        if city_match:
            provider_city = city_match.group(0)
        return heading_context, provider_name, provider_city, provider_code

    # Build processed rows
    processed_rows: list[dict] = []
    review_flags: list[dict] = []

    for chunk in raw_chunks:
        idx = chunk.get("chunk_index", 0)
        text = chunk.get("text", "")
        meta = chunk.get("meta", {})

        semantic_class, extracted_fields, confidence, needs_review = _classify_chunk(chunk)
        heading_context, provider_name, provider_city, provider_code = _extract_heading_and_provider(chunk)

        # Page number from Docling provenance
        page_no = 0
        bbox_str = "{}"
        try:
            doc_items = meta.get("doc_items", [])
            if doc_items and doc_items[0].get("prov"):
                prov = doc_items[0]["prov"][0]
                page_no = prov.get("page_no", 0)
                bbox_str = json.dumps(prov.get("bbox", {}), ensure_ascii=False)
        except Exception:
            pass

        # CMS refs in this chunk
        cms_in_chunk: list[str] = _CMS_PATTERN.findall(text)

        # Docling label
        label = ""
        try:
            doc_items = meta.get("doc_items", [])
            if doc_items:
                label = str(doc_items[0].get("label", ""))
        except Exception:
            pass

        # Build enriched text for embedding
        cms_refs_str = " ".join(cms_in_chunk)
        text_for_embed = f"[{semantic_class}] [{heading_context}] {cms_refs_str} {text}".strip()

        row = {
            "chunk_index":       idx,
            "case_id":           case_id,
            "page_no":           page_no,
            "bbox":              bbox_str,
            "label":             label,
            "heading_context":   heading_context,
            "section_path":      json.dumps([]),
            "semantic_class":    semantic_class,
            "cms_refs_found":    json.dumps(cms_in_chunk),
            "provider_name":     provider_name,
            "provider_city":     provider_city,
            "provider_code":     provider_code,
            "extracted_fields":  json.dumps(extracted_fields, ensure_ascii=False),
            "extraction_method": "pattern",
            "confidence":        confidence,
            "needs_review":      needs_review,
            "text":              text,
            "text_for_embed":    text_for_embed,
            "embedding":         [],  # filled in after batch embed call
        }
        processed_rows.append(row)

        if needs_review:
            review_flags.append({"chunk_index": idx, "semantic_class": semantic_class, "reason": "low_confidence_classification"})

    # ── 5. Batch embed via Azure OpenAI ─────────────────────────────────
    EMBED_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMBED_DEPLOYMENT", "text-embedding-3-large")
    BATCH_SIZE = 16

    try:
        oai_client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version="2024-02-01",
        )

        all_texts = [r["text_for_embed"] for r in processed_rows]
        all_embeddings: list[list[float]] = []

        for batch_start in range(0, len(all_texts), BATCH_SIZE):
            batch = all_texts[batch_start: batch_start + BATCH_SIZE]
            response = oai_client.embeddings.create(
                input=batch,
                model=EMBED_DEPLOYMENT,
                dimensions=3072,
            )
            all_embeddings.extend([item.embedding for item in response.data])
            logging.info(
                "[mtr_vectorize] embedded chunks %d-%d of %d",
                batch_start, batch_start + len(batch) - 1, len(all_texts)
            )

        for i, row in enumerate(processed_rows):
            row["embedding"] = all_embeddings[i]

    except Exception as exc:
        logging.exception("[mtr_vectorize] embedding API call failed case_id=%s", case_id)
        _update_status({"status": "vectorize_failed", "error": f"Embedding failed: {exc}"})
        return

    # ── 6. Write to LanceDB ──────────────────────────────────────────────
    try:
        mgr = LanceDBManager()
        mgr.upsert_case_chunks(case_id, processed_rows)
        table_name = "mtr_" + case_id.replace("-", "_")
        logging.info("[mtr_vectorize] LanceDB write complete: %s", table_name)
    except Exception as exc:
        logging.exception("[mtr_vectorize] LanceDB write failed case_id=%s", case_id)
        _update_status({"status": "vectorize_failed", "error": f"LanceDB write failed: {exc}"})
        return

    # ── 7. Gate 0 — completeness check ──────────────────────────────────
    REQUIRED_CLASSES = {"chemistry", "mechanical", "heat_treatment", "identity"}
    found_classes = {r["semantic_class"] for r in processed_rows}
    missing_classes = sorted(REQUIRED_CLASSES - found_classes)

    gate_0_result = "fail" if missing_classes else "pass"
    gate_0 = {
        "result":          gate_0_result,
        "required_fields": sorted(REQUIRED_CLASSES),
        "missing_fields":  missing_classes,
        "evidence":        [
            {"chunk_index": r["chunk_index"], "semantic_class": r["semantic_class"]}
            for r in processed_rows if r["semantic_class"] in REQUIRED_CLASSES
        ],
    }

    # ── 8. Gate 1 — identity + traceability check ────────────────────────
    identity_chunks = [r for r in processed_rows if r["semantic_class"] == "identity"]
    all_extracted = {}
    for r in identity_chunks:
        try:
            all_extracted.update(json.loads(r.get("extracted_fields", "{}")))
        except Exception:
            pass

    heat_number = all_extracted.get("heat_number", "")
    grade = all_extracted.get("grade", "")
    po_number = all_extracted.get("po_number", "")

    consistency_checks = [
        {"check": "heat_number_present",  "result": "pass" if heat_number else "fail"},
        {"check": "grade_present",        "result": "pass" if grade else "fail"},
        {"check": "po_number_present",    "result": "pass" if po_number else "fail"},
    ]
    gate_1_result = "pass" if all(c["result"] == "pass" for c in consistency_checks) else "fail"
    gate_1 = {
        "result":              gate_1_result,
        "heat_number":         heat_number,
        "grade":               grade,
        "po_number":           po_number,
        "consistency_checks":  consistency_checks,
        "evidence":            [
            {"chunk_index": r["chunk_index"]} for r in identity_chunks
        ],
    }

    # ── 9. Determine overall disposition signal ──────────────────────────
    has_review_flags = bool(review_flags)
    if gate_0_result == "fail" or gate_1_result == "fail":
        final_status = "under_review"
    elif has_review_flags:
        final_status = "under_review"
    else:
        final_status = "validation_ready"

    # ── 10. Build validation.json artifact ──────────────────────────────
    vectorized_at = datetime.now(timezone.utc).isoformat()
    validation_artifact = {
        "case_id":          case_id,
        "filename":         filename,
        "validated_at":     vectorized_at,
        "resolved_cms_set": resolved_cms_set,
        "lancedb_table":    table_name,
        "gate_0":           gate_0,
        "gate_1":           gate_1,
        "gate_2":           {"result": "pending", "findings": []},
        "gate_3":           {"result": "pending", "findings": []},
        "gate_4":           {"result": "open"},
        "chunk_classifications": [
            {
                "chunk_index":      r["chunk_index"],
                "semantic_class":   r["semantic_class"],
                "confidence":       r["confidence"],
                "needs_review":     r["needs_review"],
                "extracted_fields": json.loads(r.get("extracted_fields", "{}")),
                "provider_name":    r["provider_name"],
                "provider_code":    r["provider_code"],
            }
            for r in processed_rows
        ],
        "providers_identified": list({
            r["provider_name"] for r in processed_rows if r["provider_name"]
        }),
        "review_flags":      review_flags,
        "overall_disposition": "pending",
    }

    try:
        result = _store.write_mtr_validation_json(case_id, validation_artifact)
        if not result.get("success"):
            raise RuntimeError(result.get("error", "write_mtr_validation_json failed"))
        validation_blob_path = result["blob"]
        logging.info("[mtr_vectorize] wrote validation.json for case_id=%s", case_id)
    except Exception as exc:
        logging.exception("[mtr_vectorize] validation.json write failed case_id=%s", case_id)
        _update_status({"status": "vectorize_failed", "error": f"Validation artifact write failed: {exc}"})
        return

    # ── 11. Write registry row ───────────────────────────────────────────
    try:
        mgr.upsert_case_registry({
            "case_id":            case_id,
            "filename":           filename,
            "submitted_at":       payload.get("submitted_at", ""),
            "supplier_name":      next((r["provider_name"] for r in processed_rows if r["provider_name"]), ""),
            "heat_number":        heat_number,
            "grade":              grade,
            "resolved_cms_set":   json.dumps(resolved_cms_set),
            "gate_0_result":      gate_0_result,
            "gate_1_result":      gate_1_result,
            "gate_2_result":      "pending",
            "gate_3_result":      "pending",
            "gate_4_result":      "open",
            "overall_disposition":"pending",
            "chunk_count":        len(processed_rows),
            "table_name":         table_name,
            "vectorized_at":      vectorized_at,
        })
    except Exception as exc:
        logging.warning("[mtr_vectorize] registry upsert failed (non-fatal) case_id=%s: %s", case_id, exc)

    # ── 12. Final status update ──────────────────────────────────────────
    _update_status({
        "status":           final_status,
        "vectorized_at":    vectorized_at,
        "resolved_cms_set": resolved_cms_set,
        "lancedb_table":    table_name,
        "gate_results": {
            "gate_0": {"result": gate_0_result, "missing_fields": missing_classes},
            "gate_1": {"result": gate_1_result, "heat_number_match": bool(heat_number), "grade_match": bool(grade)},
            "gate_2": {"result": "pending"},
            "gate_3": {"result": "pending"},
            "gate_4": {"result": "open"},
        },
        "review_flags":  review_flags,
        "artifacts": {
            "raw":             f"mtr/{case_id}/raw/{filename}",
            "markdown":        f"mtr/{case_id}/processed/{case_id}.md",
            "chunks_jsonl":    f"mtr/{case_id}/processed/{case_id}_chunks.jsonl",
            "structured_json": f"mtr/{case_id}/processed/{case_id}_structured.json",
            "validation_json": validation_blob_path,
        },
    })
    logging.info(
        "[mtr_vectorize] complete case_id=%s status=%s gate_0=%s gate_1=%s review_flags=%d",
        case_id, final_status, gate_0_result, gate_1_result, len(review_flags)
    )