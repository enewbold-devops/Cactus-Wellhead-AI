import base64
import json
import logging
import os
import uuid
from datetime import datetime, timezone

import azure.functions as func
from azure.core.exceptions import AzureError, ResourceNotFoundError
from azure.storage.queue import QueueClient

from py_azurite_blob_storage import CactusWHDBlobStorage
from py_docling_chunks import PDFProcessor

# ------------------------------------------------------------------
# Shared clients — instantiated once at module load so TCP connections
# to Azurite / Azure Storage are reused across warm calls.
# ------------------------------------------------------------------

_MTR_QUEUE_NAME = "mtr-intake-queue"
_QUEUE_CONN_STR = os.environ.get("AzureWebJobsStorage", "UseDevelopmentStorage=true")

try:
    _store = CactusWHDBlobStorage()
except Exception as _exc:
    logging.warning("CactusWHDBlobStorage failed to initialise at module load: %s", _exc)
    _store = None  # type: ignore

try:
    _queue = QueueClient.from_connection_string(_QUEUE_CONN_STR, _MTR_QUEUE_NAME)
    _queue.create_queue()  # no-op if queue already exists
except Exception as _exc:
    logging.warning("QueueClient failed to initialise at module load: %s", _exc)
    _queue = None  # type: ignore

try:
    _processor = PDFProcessor()
except Exception as _exc:
    logging.warning("PDFProcessor failed to initialise at module load: %s", _exc)
    _processor = None  # type: ignore

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
# Helpers
# ------------------------------------------------------------------

def _utc_now() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


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
#
# Accepts a raw binary PDF body.  Caller must supply the original
# filename via the `filename` query parameter.
#
# On success returns 202 Accepted with:
#   { job_id, status, filename, queued_at, poll_url }
# ------------------------------------------------------------------

@app.route(route="mtr/intake", methods=["POST"])
def http_mtr_intake(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("[mtr/intake] request received")

    # --- resolve filename ---
    filename = req.params.get("filename", "").strip()
    if not filename:
        return _error_response(
            "Missing required query parameter: filename (e.g. ?filename=heat-1234.pdf)",
            status_code=400,
        )

    body = req.get_body()
    if not body:
        return _error_response("Request body is empty — expected raw PDF bytes.", status_code=400)

    job_id = str(uuid.uuid4())
    queued_at = _utc_now()

    try:
        # 1. Store original file
        original_url = _store.write_mtr_original(job_id, filename, body)
        logging.info("[mtr/intake] %s — original stored: %s", job_id, original_url)

        # 2. Write initial manifest
        manifest = {
            "job_id": job_id,
            "status": "queued",
            "filename": filename,
            "queued_at": queued_at,
            "original_blob": original_url,
        }
        _store.write_mtr_manifest(job_id, manifest)

        # 3. Enqueue processing message (base64-encoded JSON for Functions runtime)
        payload = json.dumps({"job_id": job_id, "filename": filename})
        _queue.send_message(base64.b64encode(payload.encode()).decode())
        logging.info("[mtr/intake] %s — queued for processing", job_id)

        return _json_response(
            {
                "job_id": job_id,
                "status": "queued",
                "filename": filename,
                "queued_at": queued_at,
                "poll_url": f"/api/mtr/status/{job_id}",
            },
            status_code=202,
        )

    except AzureError as exc:
        logging.exception("[mtr/intake] blob/queue storage error")
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[mtr/intake] unexpected error")
        return _error_response(f"Unexpected error: {exc}", 500)


# ------------------------------------------------------------------
# Route 5 — Queue trigger: mtr-intake-queue
#
# Picks up queued MTR jobs, runs Docling conversion + chunking, and
# writes chunks.jsonl back to blob.  Updates the manifest at each
# stage: queued → processing → complete | failed.
# ------------------------------------------------------------------

@app.queue_trigger(arg_name="msg", queue_name=_MTR_QUEUE_NAME, connection="AzureWebJobsStorage")
def mtr_queue_processor(msg: func.QueueMessage) -> None:
    # Decode message — the Functions runtime base64-decodes before delivery,
    # so msg.get_body() already returns the raw JSON bytes.
    try:
        payload = msg.get_json()
    except Exception:
        raw = msg.get_body().decode("utf-8")
        payload = json.loads(base64.b64decode(raw).decode("utf-8"))

    job_id: str = payload["job_id"]
    filename: str = payload["filename"]
    logging.info("[mtr/queue] %s — processing started (%s)", job_id, filename)

    # --- update manifest: processing ---
    try:
        manifest = _store.get_mtr_manifest(job_id)
    except Exception:
        manifest = {"job_id": job_id, "filename": filename}

    manifest["status"] = "processing"
    manifest["processing_started_at"] = _utc_now()
    _store.write_mtr_manifest(job_id, manifest)

    try:
        # 1. Fetch original bytes
        pdf_bytes = _store.get_mtr_original_bytes(job_id, filename)
        logging.info("[mtr/queue] %s — fetched %d bytes", job_id, len(pdf_bytes))

        # 2. Docling: convert + chunk
        _document, chunks = _processor.process_from_bytes(pdf_bytes, suffix=".pdf")
        logging.info("[mtr/queue] %s — docling produced %d chunks", job_id, len(chunks))

        # 3. Serialise to JSONL — schema mirrors cms_chunks.jsonl
        ingested_at = _utc_now()
        lines = []
        for i, chunk in enumerate(chunks):
            # Extract page range if available
            page_start = None
            page_end = None
            if hasattr(chunk, "meta") and chunk.meta:
                prov = getattr(chunk.meta, "doc_items", []) or []
                pages = []
                for item in prov:
                    for ref in getattr(item, "prov", []) or []:
                        pg = getattr(ref, "page_no", None)
                        if pg is not None:
                            pages.append(pg)
                if pages:
                    page_start = min(pages)
                    page_end = max(pages)

            # Section path from headings
            section_path = []
            if hasattr(chunk, "meta") and chunk.meta:
                for heading in getattr(chunk.meta, "headings", []) or []:
                    section_path.append(str(heading))

            record = {
                "doc": {
                    "job_id": job_id,
                    "filename": filename,
                    "source_file": filename,
                    "ingested_at": ingested_at,
                },
                "chunk": {
                    "chunk_id": f"{job_id}_{i:04d}",
                    "type": "text",
                    "section_path": section_path,
                    "page_start": page_start,
                    "page_end": page_end,
                    "text": chunk.text if hasattr(chunk, "text") else "",
                    "canonical_section": section_path[-1] if section_path else None,
                    "params": {},
                },
            }
            lines.append(json.dumps(record, ensure_ascii=False))

        # 4. Write chunks.jsonl
        chunks_url = _store.write_mtr_chunks_jsonl(job_id, lines)
        logging.info("[mtr/queue] %s — chunks written: %s", job_id, chunks_url)

        # 5. Update manifest: complete
        manifest["status"] = "complete"
        manifest["completed_at"] = _utc_now()
        manifest["chunk_count"] = str(len(lines))
        manifest["chunks_blob"] = chunks_url
        _store.write_mtr_manifest(job_id, manifest)
        logging.info("[mtr/queue] %s — complete (%d chunks)", job_id, len(lines))

    except Exception as exc:
        logging.exception("[mtr/queue] %s — processing failed", job_id)
        manifest["status"] = "failed"
        manifest["failed_at"] = _utc_now()
        manifest["error"] = str(exc)
        try:
            _store.write_mtr_manifest(job_id, manifest)
        except Exception:
            logging.exception("[mtr/queue] %s — could not write failure manifest", job_id)


# ------------------------------------------------------------------
# Route 6 — GET /api/mtr/status/{job_id}
#
# Returns the current job manifest JSON.
# 200 with manifest while queued / processing / complete / failed.
# 404 if the job_id is unrecognised.
# ------------------------------------------------------------------

@app.route(route="mtr/status/{job_id}", methods=["GET"])
def http_mtr_status(req: func.HttpRequest) -> func.HttpResponse:
    job_id = req.route_params.get("job_id", "").strip()
    logging.info("[mtr/status] request received for job_id=%s", job_id)

    if not job_id:
        return _error_response("job_id route parameter is missing.", status_code=400)

    try:
        manifest = _store.get_mtr_manifest(job_id)
        return _json_response(manifest)
    except ResourceNotFoundError:
        return _error_response(f"Job not found: {job_id}", status_code=404)
    except AzureError as exc:
        logging.exception("[mtr/status] blob storage error")
        return _error_response(f"Blob storage error: {exc}", 502)
    except Exception as exc:
        logging.exception("[mtr/status] unexpected error")
        return _error_response(f"Unexpected error: {exc}", 500)