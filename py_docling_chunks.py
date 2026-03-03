import os
import tempfile
from pathlib import Path
from docling.document_converter import DocumentConverter
from docling.chunking import HybridChunker

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


if __name__ == "__main__":
    processor = PDFProcessor(output_dir="output")

    # Example usage
    # document, chunks = processor.process("example.pdf")
    # print(f"Number of chunks: {len(chunks)}")
    # for i, chunk in enumerate(chunks):
    #     print(f"\n--- Chunk {i+1} ---")
    #     print(chunk.text)