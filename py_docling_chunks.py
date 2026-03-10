import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if "__main__" not in sys.modules: 
    import types
    sys.modules["__main__"] = types.ModuleType("__main__")

from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker

# Maps common MIME types and file extensions to the suffix Docling expects
_CONTENT_TYPE_TO_SUFFIX: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/msword": ".doc",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xls",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/tiff": ".tif",
    "image/tif": ".tif",
}

_EXT_TO_SUFFIX: dict[str, str] = {
    ".pdf": ".pdf",
    ".docx": ".docx",
    ".doc": ".doc",
    ".xlsx": ".xlsx",
    ".xls": ".xls",
    ".jpg": ".jpg",
    ".jpeg": ".jpg",
    ".png": ".png",
    ".tiff": ".tif",
    ".tif": ".tif",
}

ALLOWED_SUFFIXES: set[str] = set(_EXT_TO_SUFFIX.values())

class PDFProcessor:
    def __init__(self, output_dir: str = None):
        self.converter = DocumentConverter()
        self.chunker = HybridChunker()
        self.output_dir = Path(output_dir) if output_dir else None
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def convert(self, pdf_path: str):
        """Convert a PDF file to a Docling document."""
        pdf_path = Path(pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        result = self.converter.convert(str(pdf_path))
        return result.document

    def chunk(self, document):
        """Chunk a Docling document into smaller pieces."""
        chunks = list(self.chunker.chunk(document)) 
        return chunks

    def process(self, pdf_path: str):
        """Convert and chunk a PDF file."""
        document = self.convert(pdf_path)
        chunks = self.chunk(document)
        return document, chunks

    def process_from_bytes(self, file_bytes: bytes, suffix: str = ".pdf"):
        """
        Convert and chunk a document supplied as raw bytes.

        Writes bytes to a temporary file, runs the normal convert+chunk
        pipeline, then deletes the temp file.  The suffix controls the
        file extension passed to Docling (e.g. '.pdf', '.docx').

        Returns:
            (document, chunks) — same as process().
        """
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(file_bytes)
                tmp_path = tmp.name
            return self.process(tmp_path)
        finally:
            if tmp_path:
                Path(tmp_path).unlink(missing_ok=True)

    def process_to_markdown(self, pdf_path: str) -> str:
        """Convert a PDF to markdown string."""
        document = self.convert(pdf_path)
        return document.export_to_markdown()

    def process_directory(self, directory: str):
        """Process all PDFs in a directory."""
        directory = Path(directory)
        results = {}
        for pdf_file in directory.glob("*.pdf"):
            try:
                document, chunks = self.process(str(pdf_file))
                results[pdf_file.name] = {
                    "document": document,
                    "chunks": chunks,
                    "num_chunks": len(chunks),
                }
            except Exception as e:
                results[pdf_file.name] = {"error": str(e)}
        return results

    def save_markdown(self, pdf_path: str, output_path: str = None) -> str:
        """Convert a PDF and save the result as a markdown file."""
        markdown = self.process_to_markdown(pdf_path)
        if output_path is None:
            pdf_path = Path(pdf_path)
            output_path = (
                self.output_dir / f"{pdf_path.stem}.md"
                if self.output_dir
                else pdf_path.with_suffix(".md")
            )
        output_path = Path(output_path)
        output_path.write_text(markdown, encoding="utf-8")
        return str(output_path)

    def get_chunk_texts(self, chunks) -> list[str]:
        """Extract plain text from chunks."""
        return [chunk.text for chunk in chunks if hasattr(chunk, "text")]

    @staticmethod
    def suffix_from_content_type(content_type: str) -> str | None:
        """
        Resolve a file suffix from a MIME content-type string.

        Strips parameters (e.g. 'application/pdf; charset=utf-8' → '.pdf').
        Returns the suffix (e.g. '.pdf') or None if not recognised.
        """
        if not content_type:
            return None
        mime = content_type.split(";")[0].strip().lower()
        return _CONTENT_TYPE_TO_SUFFIX.get(mime)

    @staticmethod
    def suffix_from_filename(filename: str) -> str | None:
        """
        Resolve a normalised Docling suffix from a filename or extension string.
        Returns the suffix (e.g. '.pdf') or None if not in the allowed set.
        """
        ext = Path(filename).suffix.lower()
        return _EXT_TO_SUFFIX.get(ext)

    def process_to_structured(
        self,
        file_bytes: bytes,
        case_id: str,
        filename: str,
        suffix: str = ".pdf",
    ) -> dict:
        """
        Convert and chunk a document supplied as bytes, returning a structured
        dict suitable for writing directly to blob storage as JSON.

        Schema:
          {
            "case_id":       str,
            "filename":      str,
            "processed_at":  ISO-8601 UTC timestamp,
            "doc_metadata":  { "page_count": int, "source_file": str },
            "chunks": [
              {
                "chunk_index": int,
                "text":        str,
                "meta":        dict   # serialisable subset of Docling chunk attrs
              }, ...
            ]
          }
        """
        document, raw_chunks = self.process_from_bytes(file_bytes, suffix=suffix)

        # Extract page count safely — Docling stores pages as a dict keyed by page no.
        try:
            page_count = len(document.pages) if hasattr(document, "pages") else 0
        except Exception:
            page_count = 0

        chunks_out = []
        for idx, chunk in enumerate(raw_chunks):
            text = chunk.text if hasattr(chunk, "text") else ""
            meta: dict = {}
            # Pull serialisable metadata from chunk if available
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
            chunks_out.append({"chunk_index": idx, "text": text, "meta": meta})

        return {
            "case_id": case_id,
            "filename": filename,
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "doc_metadata": {
                "page_count": page_count,
                "source_file": filename,
            },
            "chunks": chunks_out,
        }
