import json
import os
from azure.storage.blob import BlobServiceClient

# Azurite default local emulator connection string (used when env var is not set)
_AZURITE_DEFAULT = (
    "DefaultEndpointsProtocol=http;"
    "AccountName=devstoreaccount1;"
    "AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tiqnqGl0R4hStSrpxQ==;"
    "BlobEndpoint=http://127.0.0.1:10000/devstoreaccount1;"
)

BLOB_CONNECTION_STRING = os.environ.get("BLOB_CONNECTION_STRING", _AZURITE_DEFAULT)
CONTAINER_NAME = "cactus-whd"
MTR_CONTAINER_NAME = "cactus-mtr"


class CactusWHDBlobStorage:
    """
    Client for reading Cactus WHD blobs from Azure Blob Storage (or Azurite emulator).
    Container: cactus-whd

    Connection string is resolved from the BLOB_CONNECTION_STRING environment variable.
    Falls back to the Azurite local emulator default when the variable is not set.
    """

    def __init__(
        self,
        connection_string: str = BLOB_CONNECTION_STRING,
        container: str = CONTAINER_NAME,
        container_mtr: str = MTR_CONTAINER_NAME,
        blobEndpointMTR: str = f"http://127.0.0.1:10000/devstoreaccount1/{MTR_CONTAINER_NAME}",
    ):
        self.container = container
        self._service_client = BlobServiceClient.from_connection_string(connection_string)
        self._container_client = self._service_client.get_container_client(container)
        self._container_client_mtr = self._service_client.get_container_client(container_mtr)  # for MTR evidence blobs
        self.mtrBlobEndpoint = blobEndpointMTR

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _read_blob_bytes(self, blob_name: str) -> bytes:
        """Download a blob and return its raw bytes."""
        blob_client = self._container_client.get_blob_client(blob_name)
        stream = blob_client.download_blob()
        return stream.readall()

    def _read_blob_json(self, blob_name: str) -> list | dict:
        """Download a blob and parse it as JSON."""
        raw = self._read_blob_bytes(blob_name)
        return json.loads(raw.decode("utf-8"))
    
    def _write_blob_bytes(self, blob_path: str, blob_name: str, data: bytes, overwrite: bool = True) -> dict:
        """Upload raw bytes to a blob."""
        fileblob = os.path.join("mcr", f"{blob_path}", os.path.basename(blob_name))
        try:
            blob_client = self._container_client_mtr.get_blob_client(fileblob)
            blob_client.upload_blob(data, overwrite=overwrite)
            return {"success": True, "blob": f"{self.mtrBlobEndpoint}/{fileblob}"}
        except Exception as e:
            return {"success": False, "error": str(e), "blob": f"{self.mtrBlobEndpoint}/{fileblob}"}

    def _write_blob_json(self, blob_path: str, blob_name: str, data: list | dict, overwrite: bool = True) -> dict:
        """Serialize data as JSON and upload to a blob."""
        raw = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
        return self._write_blob_bytes(blob_path, blob_name, raw, overwrite=overwrite)

    # ------------------------------------------------------------------
    # Named file methods
    # ------------------------------------------------------------------

    def get_approved_providers(self) -> list[dict]:
        """
        Return the full approved providers list from cms_approved_providers.json.
        Each record contains: provider_id, supplier_name, site_address, site_city,
        site_state, site_zip, process_code, process_name, process_category,
        parent_supplier, approval_status, last_audit_date, notes.
        """
        return self._read_blob_json("cms-rubric/cms_approved_providers.json")  # type: ignore

    def get_cms_process_crosswalk(self) -> list[dict]:
        """
        Return the CMS-to-approved-process crosswalk from cms_process_crosswalk.json.
        Each record contains: cms_spec, material_scope, mandatory_process_codes,
        conditional_process_codes, conditional_trigger, typical_mtr_evidence, sop_notes.
        """
        return self._read_blob_json("cms-rubric/cms_process_crosswalk.json")  # type: ignore

    def get_cms_chunks(self, cms_number: str) -> list[dict]:
        """
        Return all chunk records from cms-specs/cms_chunks.jsonl where
        doc.cms_number matches the given cms_number (case-sensitive).

        Each returned record is the full parsed JSON line object:
          {
            "doc":   { "cms_number", "revision", "effective_date", "title", "source_file" },
            "chunk": { "chunk_id", "type", "section_path", "page_start", "page_end",
                       "text", "canonical_section", "params" }
          }

        Args:
            cms_number: The CMS number to filter by, e.g. "CMS-002" or "CMS-305".

        Returns:
            List of matching JSON line objects; empty list if none found.
        """
        raw = self._read_blob_bytes("cms-rubric/cms-specs/cms_chunks.jsonl")
        results = []
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            if record.get("doc", {}).get("cms_number") == cms_number:
                results.append(record)
        return results

    # ------------------------------------------------------------------
    # MTR private helpers (operate on cactus-mtr container)
    # ------------------------------------------------------------------

    def _mtr_blob_path(self, job_id: str, *parts: str) -> str:
        """Build a canonical blob path inside cactus-mtr: mcr/{job_id}/{parts}."""
        return "/".join(["mcr", job_id, *parts])

    def _read_mtr_blob_bytes(self, blob_path: str) -> bytes:
        """Download a blob from cactus-mtr and return raw bytes."""
        blob_client = self._container_client_mtr.get_blob_client(blob_path)
        return blob_client.download_blob().readall()

    def _upload_mtr_blob_bytes(self, blob_path: str, data: bytes, overwrite: bool = True) -> str:
        """Upload raw bytes to cactus-mtr; returns the full blob URL."""
        blob_client = self._container_client_mtr.get_blob_client(blob_path)
        blob_client.upload_blob(data, overwrite=overwrite)
        return f"{self.mtrBlobEndpoint}/{blob_path}"

    # ------------------------------------------------------------------
    # MTR public methods
    # ------------------------------------------------------------------

    def write_mtr_original(self, job_id: str, filename: str, data: bytes) -> str:
        """
        Store the raw uploaded MTR file.
        Blob path: mcr/{job_id}/original/{filename}
        Returns the blob URL.
        """
        path = self._mtr_blob_path(job_id, "original", filename)
        return self._upload_mtr_blob_bytes(path, data)

    def write_mtr_manifest(self, job_id: str, manifest: dict) -> str:
        """
        Write (or overwrite) the job manifest JSON.
        Blob path: mcr/{job_id}/job.json
        Returns the blob URL.
        """
        path = self._mtr_blob_path(job_id, "job.json")
        raw = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
        return self._upload_mtr_blob_bytes(path, raw)

    def write_mtr_chunks_jsonl(self, job_id: str, lines: list[str]) -> str:
        """
        Write chunk records as JSONL (one JSON object per line).
        Blob path: mcr/{job_id}/chunks.jsonl
        Returns the blob URL.
        """
        path = self._mtr_blob_path(job_id, "chunks.jsonl")
        raw = "\n".join(lines).encode("utf-8")
        return self._upload_mtr_blob_bytes(path, raw)

    def get_mtr_manifest(self, job_id: str) -> dict:
        """
        Read and parse the job manifest JSON.
        Raises azure.core.exceptions.ResourceNotFoundError if job_id not found.
        """
        path = self._mtr_blob_path(job_id, "job.json")
        raw = self._read_mtr_blob_bytes(path)
        return json.loads(raw.decode("utf-8"))

    def get_mtr_chunks(self, job_id: str) -> list[dict]:
        """
        Read and parse all chunk records from chunks.jsonl.
        Returns list of parsed JSON objects; empty list if file is empty.
        """
        path = self._mtr_blob_path(job_id, "chunks.jsonl")
        raw = self._read_mtr_blob_bytes(path)
        results = []
        for line in raw.decode("utf-8").splitlines():
            line = line.strip()
            if line:
                results.append(json.loads(line))
        return results

    def get_mtr_original_bytes(self, job_id: str, filename: str) -> bytes:
        """
        Download the original uploaded MTR file as raw bytes.
        Blob path: mcr/{job_id}/original/{filename}
        """
        path = self._mtr_blob_path(job_id, "original", filename)
        return self._read_mtr_blob_bytes(path)

    # ------------------------------------------------------------------
    # General blob utilities
    # ------------------------------------------------------------------

    def list_blobs(self) -> list[str]:
        """Return a list of all blob names in the container."""
        return [b.name for b in self._container_client.list_blobs()]

    def read_blob_json(self, blob_name: str) -> list | dict:
        """Generic method: download any JSON blob by name and return parsed object."""
        return self._read_blob_json(blob_name)

    def read_blob_text(self, blob_name: str, encoding: str = "utf-8") -> str:
        """Generic method: download any text blob by name and return as string."""
        return self._read_blob_bytes(blob_name).decode(encoding)

    def read_blob_bytes(self, blob_name: str) -> bytes:
        """Generic method: download any blob by name and return raw bytes."""
        return self._read_blob_bytes(blob_name)
    


# ------------------------------------------------------------------
# Quick smoke test (run this file directly to verify connectivity)
# ------------------------------------------------------------------

if __name__ == "__main__":
    client = CactusWHDBlobStorage()

    print("=== Blobs in container ===")
    for name in client.list_blobs():
        print(f"  {name}")

    print("\n=== Approved Providers (first 3) ===")
    providers = client.get_approved_providers()
    for p in providers[:3]:
        print(f"  [{p['provider_id']}] {p['supplier_name']} | {p['process_code']} | {p['site_city']}, {p['site_state']}")

    print("\n=== CMS Process Crosswalk ===")
    crosswalk = client.get_cms_process_crosswalk()
    for entry in crosswalk:
        print(f"  {entry['cms_spec']}: mandatory={entry['mandatory_process_codes']}")

    print("\n=== CMS Chunks — CMS-002 (first 3) ===")
    chunks = client.get_cms_chunks("CMS-002")
    print(f"  Total chunks matched: {len(chunks)}")
    for c in chunks[:3]:
        print(f"  [{c['chunk']['chunk_id']}] section={c['chunk']['canonical_section']} p{c['chunk']['page_start']}")
