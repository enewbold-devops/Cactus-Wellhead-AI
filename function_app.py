import base64
import json
import logging
import uuid
from datetime import datetime, timezone


from azure.core.exceptions import AzureError
from py_azurite_blob_storage import CactusWHDBlobStorage
from py_azurite_queue_storage import AzuriteQueueManager

import azure.functions as func

MTR_INTAKE_QUEUE = "mtr-intake-queue"

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