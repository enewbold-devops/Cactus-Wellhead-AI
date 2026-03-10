"""
py_vectodb.py — LanceDB vector store manager for Cactus WHD MTR validation pipeline.

Two primary stores:
  1. cms_spec_chunks   — shared, static CMS specification knowledge base
  2. mtr_{case_id}     — per-case MTR chunk vectors (one table per case)
  3. mtr_case_registry — flat (no vector) cross-case index for analytics

All write operations are guarded by a module-level threading.Lock (mutex) to
prevent concurrent write corruption when multiple Azure Functions workers share
the same process. For cross-process safety on Windows, a filelock is also
acquired on a sentinel file before any LanceDB open/write sequence.

Connection: lancedb.connect(LANCEDB_PATH) — embedded, no server required.
Path:       Resolved from LANCEDB_PATH env var (no trailing slash).
Embedding:  text-embedding-3-large via Azure OpenAI — dimensions=3072.
            Caller is responsible for providing pre-computed float lists;
            this module stores them but does not call the embedding API.
"""

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

import lancedb
import numpy as np
import pyarrow as pa
from filelock import FileLock

# ------------------------------------------------------------------
# Configuration
# ------------------------------------------------------------------

LANCEDB_PATH: str = os.environ.get(
    "LANCEDB_PATH",
    str(Path(__file__).parent / "vectordb_lancedb"),
)

EMBED_DIMS: int = 3072          # text-embedding-3-large full dimensions
_SENTINEL_LOCK_PATH: str = str(Path(LANCEDB_PATH) / ".lancedb_write.lock")
_VECTOR_TYPE = pa.list_(pa.float32(), EMBED_DIMS)   # canonical fixed_size_list embedding type

# ------------------------------------------------------------------
# Module-level concurrency primitives
# ------------------------------------------------------------------

_THREAD_LOCK = threading.Lock()          # in-process mutex (fast path)
_db_cache_lock = threading.Lock()        # guards _db_cache singleton creation
_db_cache: lancedb.DBConnection | None = None

# ------------------------------------------------------------------
# PyArrow schemas
# ------------------------------------------------------------------

MTR_CASE_SCHEMA = pa.schema([
    pa.field("chunk_index",       pa.int32()),
    pa.field("case_id",           pa.string()),
    pa.field("page_no",           pa.int32()),
    pa.field("bbox",              pa.string()),          # JSON: {l,t,r,b}
    pa.field("label",             pa.string()),          # Docling structural label
    pa.field("heading_context",   pa.string()),
    pa.field("section_path",      pa.string()),          # JSON list
    pa.field("semantic_class",    pa.string()),          # classified category
    pa.field("cms_refs_found",    pa.string()),          # JSON list
    pa.field("provider_name",     pa.string()),
    pa.field("provider_city",     pa.string()),
    pa.field("provider_code",     pa.string()),
    pa.field("extracted_fields",  pa.string()),          # JSON dict
    pa.field("extraction_method", pa.string()),          # "pattern"|"llm"|"vision"
    pa.field("confidence",        pa.float32()),
    pa.field("needs_review",      pa.bool_()),
    pa.field("text",              pa.string()),          # raw chunk text
    pa.field("text_for_embed",    pa.string()),          # enriched composite
    pa.field("embedding",         pa.list_(pa.float32(), EMBED_DIMS)),
])

CMS_SPEC_SCHEMA = pa.schema([
    pa.field("id",                pa.string()),
    pa.field("cms_number",        pa.string()),
    pa.field("revision",          pa.string()),
    pa.field("effective_date",    pa.string()),
    pa.field("canonical_section", pa.string()),
    pa.field("section_path",      pa.string()),          # JSON list
    pa.field("page_start",        pa.int32()),
    pa.field("text",              pa.string()),
    pa.field("params",            pa.string()),          # JSON: {lo, hi, unit, element}
    pa.field("embedding",         pa.list_(pa.float32(), EMBED_DIMS)),
])

REGISTRY_SCHEMA = pa.schema([
    pa.field("case_id",           pa.string()),
    pa.field("filename",          pa.string()),
    pa.field("submitted_at",      pa.string()),
    pa.field("supplier_name",     pa.string()),
    pa.field("heat_number",       pa.string()),
    pa.field("grade",             pa.string()),
    pa.field("resolved_cms_set",  pa.string()),          # JSON list
    pa.field("gate_0_result",     pa.string()),
    pa.field("gate_1_result",     pa.string()),
    pa.field("gate_2_result",     pa.string()),
    pa.field("gate_3_result",     pa.string()),
    pa.field("gate_4_result",     pa.string()),
    pa.field("overall_disposition", pa.string()),
    pa.field("chunk_count",       pa.int32()),
    pa.field("table_name",        pa.string()),
    pa.field("vectorized_at",     pa.string()),
])

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _get_db() -> lancedb.DBConnection:
    """Return a cached LanceDB connection (thread-safe double-checked locking)."""
    global _db_cache
    if _db_cache is None:
        with _db_cache_lock:
            if _db_cache is None:
                Path(LANCEDB_PATH).mkdir(parents=True, exist_ok=True)
                _db_cache = lancedb.connect(LANCEDB_PATH)
                logging.info("[vectodb] connected to LanceDB at %s", LANCEDB_PATH)
    return _db_cache


def _case_table_name(case_id: str) -> str:
    """Convert a UUID case_id to a safe LanceDB table name."""
    return "mtr_" + case_id.replace("-", "_")


def _safe_str(value: Any) -> str:
    """Coerce a value to string; JSON-encode lists/dicts."""
    if value is None:
        return ""
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def _schema_is_compatible(table_name: str, expected_schema: pa.Schema) -> bool:
    """
    Return True if the on-disk table schema matches expected_schema field-by-field.
    Returns True (compatible) if the table does not yet exist — it will be created fresh.
    Returns False on any field name or type mismatch, or on error.
    """
    try:
        db = _get_db()
        if table_name not in db.table_names():
            return True  # Table doesn't exist yet — will be created correctly
        tbl = db.open_table(table_name)
        stored = tbl.schema
        if stored.names != expected_schema.names:
            logging.warning(
                "[vectodb] schema field names mismatch on table %s: stored=%s expected=%s",
                table_name, stored.names, expected_schema.names,
            )
            return False
        for stored_field, expected_field in zip(stored, expected_schema):
            if stored_field.type != expected_field.type:
                logging.warning(
                    "[vectodb] schema type mismatch on table %s field '%s': "
                    "stored=%s expected=%s",
                    table_name, stored_field.name, stored_field.type, expected_field.type,
                )
                return False
        return True
    except Exception as exc:
        logging.error("[vectodb] _schema_is_compatible error on table %s: %s", table_name, exc)
        return False  # Assume incompatible on error — will drop and recreate


def _drop_and_recreate(table_name: str, arrow_table: pa.Table, schema: pa.Schema) -> None:
    """
    Drop a corrupt/mismatched table and recreate it with the correct schema.
    Must be called while holding _THREAD_LOCK and FileLock.
    """
    db = _get_db()
    if table_name in db.table_names():
        db.drop_table(table_name)
        logging.warning("[vectodb] dropped corrupt/mismatched table: %s", table_name)
    db.create_table(table_name, data=arrow_table, schema=schema)
    logging.info("[vectodb] recreated table with correct schema: %s", table_name)


# ------------------------------------------------------------------
# LanceDBManager
# ------------------------------------------------------------------

class LanceDBManager:
    """
    Manages LanceDB tables for the Cactus WHD MTR vectorization pipeline.

    Thread-safe: all write operations acquire a module-level threading.Lock
    and a cross-process filelock before touching LanceDB.

    Usage:
        mgr = LanceDBManager()
        mgr.upsert_case_chunks(case_id, rows)
        results = mgr.query_case_table(case_id, query_vector, limit=5)
    """

    # ── Table access ──────────────────────────────────────────────

    def get_or_create_cms_table(self) -> lancedb.table.Table:
        """Return the shared CMS spec chunks table, creating it if absent."""
        db = _get_db()
        names = db.table_names()
        if "cms_spec_chunks" not in names:
            tbl = db.create_table("cms_spec_chunks", schema=CMS_SPEC_SCHEMA)
            logging.info("[vectodb] created table: cms_spec_chunks")
        else:
            tbl = db.open_table("cms_spec_chunks")
        return tbl

    def get_or_create_case_table(self, case_id: str) -> lancedb.table.Table:
        """Return the per-case MTR chunk table, creating it if absent."""
        db = _get_db()
        name = _case_table_name(case_id)
        names = db.table_names()
        if name not in names:
            tbl = db.create_table(name, schema=MTR_CASE_SCHEMA)
            logging.info("[vectodb] created table: %s", name)
        else:
            tbl = db.open_table(name)
        return tbl

    def get_or_create_registry_table(self) -> lancedb.table.Table:
        """Return the flat case registry table, creating it if absent."""
        db = _get_db()
        names = db.table_names()
        if "mtr_case_registry" not in names:
            tbl = db.create_table("mtr_case_registry", schema=REGISTRY_SCHEMA)
            logging.info("[vectodb] created table: mtr_case_registry")
        else:
            tbl = db.open_table("mtr_case_registry")
        return tbl

    # ── Write operations (mutex-guarded) ─────────────────────────

    def upsert_case_chunks(self, case_id: str, rows: list[dict]) -> int:
        """
        Write/overwrite all chunk rows for a case into the per-case table.

        Each row must match MTR_CASE_SCHEMA. The embedding field must be a
        list[float] of length EMBED_DIMS (3072).

        Returns the number of rows written.
        """
        if not rows:
            logging.warning("[vectodb] upsert_case_chunks called with empty rows for %s", case_id)
            return 0

        pa_rows = _rows_to_arrow(rows, MTR_CASE_SCHEMA)

        with _THREAD_LOCK:
            with FileLock(_SENTINEL_LOCK_PATH, timeout=30):
                table_name = _case_table_name(case_id)
                if not _schema_is_compatible(table_name, MTR_CASE_SCHEMA):
                    _drop_and_recreate(table_name, pa_rows, MTR_CASE_SCHEMA)
                else:
                    tbl = self.get_or_create_case_table(case_id)
                    # Overwrite strategy: delete existing rows for case then add fresh
                    try:
                        tbl.delete(f"case_id = '{case_id}'")
                    except Exception:
                        pass  # Table may be empty — delete is best-effort
                    tbl.add(pa_rows)
                logging.info("[vectodb] wrote %d chunk rows for case %s", len(rows), case_id)

        return len(rows)

    def upsert_cms_chunks(self, rows: list[dict]) -> int:
        """
        Write CMS spec chunk rows into the shared cms_spec_chunks table.
        Deduplicates by id — existing rows with the same id are replaced.

        Returns the number of rows written.
        """
        if not rows:
            return 0

        pa_rows = _rows_to_arrow(rows, CMS_SPEC_SCHEMA)

        with _THREAD_LOCK:
            with FileLock(_SENTINEL_LOCK_PATH, timeout=30):
                if not _schema_is_compatible("cms_spec_chunks", CMS_SPEC_SCHEMA):
                    _drop_and_recreate("cms_spec_chunks", pa_rows, CMS_SPEC_SCHEMA)
                else:
                    tbl = self.get_or_create_cms_table()
                    ids = [r["id"] for r in rows]
                    for chunk_id in ids:
                        try:
                            tbl.delete(f"id = '{chunk_id}'")
                        except Exception:
                            pass
                    tbl.add(pa_rows)
                logging.info("[vectodb] wrote %d CMS spec chunk rows", len(rows))

        return len(rows)

    def upsert_case_registry(self, record: dict) -> None:
        """
        Insert or replace a single case registry record.
        Identified by case_id — any existing row for the same case_id is removed first.
        """
        pa_rows = _rows_to_arrow([record], REGISTRY_SCHEMA)

        with _THREAD_LOCK:
            with FileLock(_SENTINEL_LOCK_PATH, timeout=30):
                cid = record.get("case_id", "")
                if not _schema_is_compatible("mtr_case_registry", REGISTRY_SCHEMA):
                    _drop_and_recreate("mtr_case_registry", pa_rows, REGISTRY_SCHEMA)
                else:
                    tbl = self.get_or_create_registry_table()
                    try:
                        tbl.delete(f"case_id = '{cid}'")
                    except Exception:
                        pass
                    tbl.add(pa_rows)
                logging.info("[vectodb] upserted registry record for case %s", cid)

    def build_cms_index(self) -> None:
        """
        Build an IVF-PQ ANN index on the cms_spec_chunks embedding column.
        Call this once after seeding the CMS spec store. Safe to re-call —
        LanceDB will replace the existing index.
        """
        with _THREAD_LOCK:
            with FileLock(_SENTINEL_LOCK_PATH, timeout=30):
                tbl = self.get_or_create_cms_table()
                row_count = tbl.count_rows()
                if row_count < 256:
                    logging.warning(
                        "[vectodb] cms_spec_chunks has only %d rows — "
                        "skipping IVF-PQ index (minimum 256 recommended). "
                        "Flat search will be used.", row_count
                    )
                    return
                tbl.create_index(
                    metric="cosine",
                    vector_column_name="embedding",
                    index_type="IVF_PQ",
                    num_partitions=min(32, row_count // 8),
                    num_sub_vectors=16,
                    replace=True,
                )
                logging.info("[vectodb] built IVF-PQ index on cms_spec_chunks (%d rows)", row_count)

    # ── Read operations (no mutex needed) ────────────────────────

    def query_case_table(
        self,
        case_id: str,
        query_vector: list[float],
        limit: int = 5,
        semantic_class_filter: str | None = None,
    ) -> list[dict]:
        """
        Flat vector search over a per-case table.
        At ~37 chunks, flat search is faster and more accurate than IVF-PQ.

        Args:
            case_id:               Case UUID to search.
            query_vector:          Embedding vector (list of 3072 floats).
            limit:                 Max number of results to return.
            semantic_class_filter: If provided, pre-filter to this class only.

        Returns:
            List of matching chunk dicts with all schema columns.
        """
        try:
            tbl = self.get_or_create_case_table(case_id)
            q = tbl.search(query_vector, vector_column_name="embedding")
            if semantic_class_filter:
                q = q.where(f"semantic_class = '{semantic_class_filter}'", prefilter=True)
            results = q.limit(limit).to_list()
            return results
        except Exception as exc:
            logging.error("[vectodb] query_case_table failed case=%s: %s", case_id, exc)
            return []

    def query_cms_table(
        self,
        query_vector: list[float],
        cms_numbers: list[str] | None = None,
        canonical_section: str | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """
        Vector search over cms_spec_chunks, optionally pre-filtered by
        cms_number and/or canonical_section.

        Args:
            query_vector:       Embedding vector (list of 3072 floats).
            cms_numbers:        If provided, restrict to these CMS specs.
            canonical_section:  If provided, restrict to this section type.
            limit:              Max number of results.

        Returns:
            List of matching CMS spec chunk dicts.
        """
        try:
            tbl = self.get_or_create_cms_table()
            q = tbl.search(query_vector, vector_column_name="embedding")

            filters: list[str] = []
            if cms_numbers:
                quoted = ", ".join(f"'{c}'" for c in cms_numbers)
                filters.append(f"cms_number IN ({quoted})")
            if canonical_section:
                filters.append(f"canonical_section = '{canonical_section}'")
            if filters:
                q = q.where(" AND ".join(filters), prefilter=True)

            return q.limit(limit).to_list()
        except Exception as exc:
            logging.error("[vectodb] query_cms_table failed: %s", exc)
            return []

    def query_case_chunks_for_eval(
        self,
        case_id: str,
        query_vector: list[float],
        semantic_classes: list[str] | None = None,
        limit: int = 8,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Vector search over a per-case MTR table for the Requirement Evaluator.

        Supports multi-class pre-filtering and returns results with a
        'vector_score' field (cosine similarity: 1 − distance, range 0–1).

        Args:
            case_id:          Case UUID.
            query_vector:     Embedded requirement text (3072 floats).
            semantic_classes: If provided, restrict to these classes
                              (e.g. ["chemistry", "mechanical"]).
            limit:            Max hits to return before score filtering.
            min_score:        Discard hits below this cosine similarity.

        Returns:
            List of matching chunk dicts, each extended with 'vector_score'.
        """
        try:
            tbl = self.get_or_create_case_table(case_id)
            q = tbl.search(query_vector, vector_column_name="embedding")
            if semantic_classes:
                quoted = ", ".join(f"'{c}'" for c in semantic_classes)
                q = q.where(f"semantic_class IN ({quoted})", prefilter=True)
            results = q.limit(limit).to_list()
            out = []
            for row in results:
                dist = row.pop("_distance", None)
                score = round(1.0 - float(dist), 4) if dist is not None else None
                if min_score and score is not None and score < min_score:
                    continue
                row["vector_score"] = score
                out.append(row)
            return out
        except Exception as exc:
            logging.error(
                "[vectodb] query_case_chunks_for_eval failed case=%s: %s", case_id, exc
            )
            return []

    def query_cms_table_for_eval(
        self,
        query_vector: list[float],
        cms_numbers: list[str] | None = None,
        canonical_section: str | None = None,
        limit: int = 8,
        min_score: float = 0.0,
    ) -> list[dict]:
        """
        Vector search over the shared CMS spec chunks table for the Requirement
        Evaluator. Returns hits with 'vector_score' (cosine similarity 0–1).

        Args:
            query_vector:      Embedded requirement text (3072 floats).
            cms_numbers:       If provided, restrict to these CMS specs.
            canonical_section: If provided, restrict to this section type.
            limit:             Max hits before score filtering.
            min_score:         Discard hits below this cosine similarity.

        Returns:
            List of matching CMS spec chunk dicts, each with 'vector_score'.
        """
        try:
            tbl = self.get_or_create_cms_table()
            q = tbl.search(query_vector, vector_column_name="embedding")
            filters: list[str] = []
            if cms_numbers:
                quoted = ", ".join(f"'{c}'" for c in cms_numbers)
                filters.append(f"cms_number IN ({quoted})")
            if canonical_section:
                filters.append(f"canonical_section = '{canonical_section}'")
            if filters:
                q = q.where(" AND ".join(filters), prefilter=True)
            results = q.limit(limit).to_list()
            out = []
            for row in results:
                dist = row.pop("_distance", None)
                score = round(1.0 - float(dist), 4) if dist is not None else None
                if min_score and score is not None and score < min_score:
                    continue
                row["vector_score"] = score
                out.append(row)
            return out
        except Exception as exc:
            logging.error("[vectodb] query_cms_table_for_eval failed: %s", exc)
            return []

    def get_case_chunks(self, case_id: str) -> list[dict]:
        """
        Return all rows from a per-case table ordered by chunk_index.
        Used by the validation layer to iterate all chunks after vectorization.
        """
        try:
            tbl = self.get_or_create_case_table(case_id)
            return tbl.search().limit(10_000).to_list()
        except Exception as exc:
            logging.error("[vectodb] get_case_chunks failed case=%s: %s", case_id, exc)
            return []

    def get_registry_record(self, case_id: str) -> dict | None:
        """Return the registry record for a case, or None if not found."""
        try:
            tbl = self.get_or_create_registry_table()
            rows = tbl.search().where(f"case_id = '{case_id}'", prefilter=True).limit(1).to_list()
            return rows[0] if rows else None
        except Exception as exc:
            logging.error("[vectodb] get_registry_record failed case=%s: %s", case_id, exc)
            return None

    def list_case_tables(self) -> list[str]:
        """Return names of all per-case MTR tables (excludes registry and CMS table)."""
        db = _get_db()
        return [
            t for t in db.table_names()
            if t.startswith("mtr_") and t != "mtr_case_registry"
        ]

    def drop_case_table(self, case_id: str) -> bool:
        """
        Delete the per-case LanceDB table. Used for retention/cleanup.
        Returns True if dropped, False if the table did not exist.
        """
        db = _get_db()
        name = _case_table_name(case_id)
        with _THREAD_LOCK:
            with FileLock(_SENTINEL_LOCK_PATH, timeout=30):
                if name in db.table_names():
                    db.drop_table(name)
                    logging.info("[vectodb] dropped table: %s", name)
                    return True
                return False

    def case_table_exists(self, case_id: str) -> bool:
        """Return True if a per-case table already exists for this case_id."""
        db = _get_db()
        return _case_table_name(case_id) in db.table_names()

    def cms_table_row_count(self) -> int:
        """Return the number of rows in the CMS spec chunks table."""
        try:
            return self.get_or_create_cms_table().count_rows()
        except Exception:
            return 0


# ------------------------------------------------------------------
# Internal: PyArrow batch builder
# ------------------------------------------------------------------

def _rows_to_arrow(rows: list[dict], schema: pa.Schema) -> pa.Table:
    """
    Convert a list of row dicts to a PyArrow Table conforming to `schema`.

    - String fields: coerced via _safe_str.
    - bool fields:   coerced to bool.
    - int32 fields:  coerced to int, defaulting to 0.
    - float32 fields: coerced to float, defaulting to 0.0.
    - Embedding (list<float32>[3072]): passed through as-is; validated for length.
    """
    if not rows:
        return pa.table({f.name: pa.array([], type=f.type) for f in schema}, schema=schema)

    columns: dict[str, list] = {field.name: [] for field in schema}

    for row in rows:
        for field in schema:
            name = field.name
            raw = row.get(name)

            if pa.types.is_fixed_size_list(field.type):
                # Embedding vector column
                if raw is None:
                    columns[name].append([0.0] * EMBED_DIMS)
                else:
                    vec = list(raw)
                    if len(vec) != EMBED_DIMS:
                        logging.warning(
                            "[vectodb] embedding length mismatch: expected %d got %d — zero-padding",
                            EMBED_DIMS, len(vec)
                        )
                        vec = (vec + [0.0] * EMBED_DIMS)[:EMBED_DIMS]
                    columns[name].append(vec)
            elif field.type == pa.bool_():
                columns[name].append(bool(raw) if raw is not None else False)
            elif field.type == pa.int32():
                try:
                    columns[name].append(int(raw) if raw is not None else 0)
                except (ValueError, TypeError):
                    columns[name].append(0)
            elif field.type == pa.float32():
                try:
                    columns[name].append(float(raw) if raw is not None else 0.0)
                except (ValueError, TypeError):
                    columns[name].append(0.0)
            else:
                # All other fields → string
                columns[name].append(_safe_str(raw))

    arrays = []
    for field in schema:
        if pa.types.is_fixed_size_list(field.type):
            # PyArrow cannot auto-cast list<double> → fixed_size_list<float32>[N].
            # Build a (rows × EMBED_DIMS) float32 numpy matrix, flatten it into a
            # typed pa.float32() buffer, then wrap with FixedSizeListArray.
            raw_vecs = columns[field.name]
            np_matrix = np.zeros((len(raw_vecs), EMBED_DIMS), dtype=np.float32)
            for i, vec in enumerate(raw_vecs):
                if vec and len(vec) == EMBED_DIMS:
                    np_matrix[i] = np.asarray(vec, dtype=np.float32)
            flat_buf = pa.array(np_matrix.flatten().tolist(), type=pa.float32())
            arr = pa.FixedSizeListArray.from_arrays(flat_buf, EMBED_DIMS)
        elif field.type == pa.bool_():
            arr = pa.array(columns[field.name], type=pa.bool_())
        elif field.type == pa.int32():
            arr = pa.array(columns[field.name], type=pa.int32())
        elif field.type == pa.float32():
            arr = pa.array(columns[field.name], type=pa.float32())
        else:
            arr = pa.array(columns[field.name], type=pa.string())
        arrays.append(arr)

    return pa.table(arrays, schema=schema)
