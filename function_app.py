import json
import logging

import azure.functions as func
from azure.core.exceptions import AzureError

from blob_storage import CactusWHDBlobStorage

# ------------------------------------------------------------------
# Shared client — instantiated once at module load so the TCP
# connection to Azurite / Azure Storage is reused across warm calls.
# ------------------------------------------------------------------
try:
    _store = CactusWHDBlobStorage()
except Exception as _exc:
    logging.warning("CactusWHDBlobStorage failed to initialise at module load: %s", _exc)
    _store = None  # type: ignore

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