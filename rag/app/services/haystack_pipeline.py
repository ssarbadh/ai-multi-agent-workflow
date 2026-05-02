"""Haystack pipeline for document indexing."""
import logging
from typing import Dict, Any, List, Optional

from haystack import Pipeline
from haystack.dataclasses import ByteStream
from haystack.components.converters import PyPDFToDocument, TextFileToDocument
from haystack.components.preprocessors import DocumentSplitter, DocumentCleaner
from haystack.components.writers import DocumentWriter
from haystack.document_stores.types import DuplicatePolicy

from app.core.config import settings
from sqlalchemy import text
from app.core.database import AsyncSessionLocal
from app.models.models import Document
from app.services.haystack_store import get_postgres_document_store
from app.services.embeddings import embedding_service
from app.services.gdrive import gdrive_service
from app.services.cache import cache_manager

logger = logging.getLogger(__name__)


class IndexingPipeline:
    """Haystack indexing pipeline for document processing."""

    def __init__(self):
        """Initialize indexing pipeline."""
        self.document_store = get_postgres_document_store()
        self.pipeline = self._build_pipeline()
        logger.info("Indexing pipeline initialized")

    def _build_pipeline(self) -> Pipeline:
        """Build Haystack indexing pipeline."""
        pipeline = Pipeline()

        # Add components
        pipeline.add_component("pdf_converter", PyPDFToDocument())
        pipeline.add_component("text_converter", TextFileToDocument())

        # Add document joiner to merge outputs from converters
        from haystack.components.joiners import DocumentJoiner

        pipeline.add_component("joiner", DocumentJoiner())

        pipeline.add_component("cleaner", DocumentCleaner())
        pipeline.add_component(
            "splitter",
            DocumentSplitter(
                split_by="word",  # Use word-based splitting
                split_length=settings.rag_chunk_size,
                split_overlap=settings.rag_chunk_overlap,
            ),
        )
        pipeline.add_component(
            "writer",
            DocumentWriter(
                document_store=self.document_store,
                policy=DuplicatePolicy.OVERWRITE,
            ),
        )

        # Connect components with joiner
        pipeline.connect("pdf_converter.documents", "joiner")
        pipeline.connect("text_converter.documents", "joiner")
        pipeline.connect("joiner.documents", "cleaner.documents")
        pipeline.connect("cleaner.documents", "splitter.documents")
        pipeline.connect("splitter.documents", "writer.documents")

        return pipeline

    def _determine_document_type(self, file_metadata: Dict[str, Any], content: str) -> str:
        """
        Determine document type based on file metadata and content.

        Returns one of: incident, runbook, procedure, kb_article, general
        """
        file_name = file_metadata.get("name", "").lower()
        content_lower = content.lower()

        # Check filename patterns
        if any(pattern in file_name for pattern in ["incident", "inc", "sop", "runbook"]):
            if "incident" in file_name or "inc" in file_name:
                return "incident"
            elif "runbook" in file_name:
                return "runbook"
            elif "sop" in file_name:
                return "procedure"

        # Check content patterns
        if any(pattern in content_lower for pattern in ["incident", "outage", "p1", "p2", "severity"]):
            return "incident"
        elif any(pattern in content_lower for pattern in ["runbook", "playbook", "procedure"]):
            return "runbook"
        elif "standard operating procedure" in content_lower or "sop" in content_lower:
            return "procedure"
        elif any(pattern in content_lower for pattern in ["kb", "knowledge base", "how to", "guide"]):
            return "kb_article"

        return "general"

    async def run_async(self, file_id: str, file_metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        Run indexing pipeline asynchronously for a single file.

        Args:
            file_id: Google Drive file ID
            file_metadata: File metadata from Google Drive

        Returns:
            Indexing result with chunks created
        """
        try:
            logger.info(f"Indexing file: {file_metadata.get('name')} ({file_id})")

            # Download file content
            mime_type = file_metadata.get("mimeType", "")
            content = gdrive_service.download_file(file_id=file_id, mime_type=mime_type)
            if not content:
                raise ValueError(f"Failed to download file {file_id}")

            filename = file_metadata.get("name", "document")

            # DOCX is ZIP + OOXML; TextFileToDocument expects plain text bytes. Extract with python-docx first.
            is_docx = (
                "wordprocessingml" in (mime_type or "").lower()
                or filename.lower().endswith(".docx")
            )

            if is_docx:
                extracted = gdrive_service.extract_text(
                    content=content,
                    mime_type=mime_type or "",
                    filename=filename,
                )
                if not extracted or len(extracted.strip()) < 10:
                    raise ValueError(f"No extractable text from DOCX: {filename}")
                stream_bytes = extracted.encode("utf-8")
                stream_mime = "text/plain"
            else:
                stream_bytes = content
                stream_mime = mime_type or "application/octet-stream"

            # Determine document type (plain-text preview only when we already extracted)
            preview_for_type = extracted if is_docx else ""
            document_type = self._determine_document_type(file_metadata, preview_for_type)

            # Haystack Pipeline requires inputs for every root component. Two converters merge in
            # DocumentJoiner — the unused branch gets empty sources ([], not omitted).
            byte_stream = ByteStream(
                data=stream_bytes,
                meta={"mime_type": stream_mime, "file_path": filename},
            )

            if "pdf" in (mime_type or "").lower():
                result = self.pipeline.run(
                    {
                        "pdf_converter": {"sources": [byte_stream]},
                        "text_converter": {"sources": []},
                    },
                    include_outputs_from={"splitter"},
                )
            else:
                result = self.pipeline.run(
                    {
                        "pdf_converter": {"sources": []},
                        "text_converter": {"sources": [byte_stream]},
                    },
                    include_outputs_from={"splitter"},
                )

            # Update Haystack documents with document_type
            # Persist classification inside Haystack meta JSON for compatibility.
            async with AsyncSessionLocal() as session:
                chunks_created = 0

                for idx, doc in enumerate(result.get("splitter", {}).get("documents", [])):
                    # Detect confidentiality
                    confidentiality = self._detect_confidentiality(doc.content)

                    # Generate embedding
                    embedding = await embedding_service.embed_text(doc.content)

                    doc_id = f"{file_id}_{idx}"

                    # Update Haystack table metadata with document_type
                    await session.execute(
                        text(
                            """
                        UPDATE haystack_rag_documents
                        SET meta = COALESCE(meta, '{}'::jsonb) || jsonb_build_object('document_type', :doc_type)
                        WHERE id = :doc_id
                        """
                        ),
                        {"doc_type": document_type, "doc_id": doc_id},
                    )

                    # Create document record in our table
                    db_doc = Document(
                        id=doc_id,
                        content=doc.content,
                        title=file_metadata.get("name"),
                        source="google_drive",
                        file_id=file_id,
                        file_path=file_metadata.get("name"),
                        chunk_index=idx,
                        total_chunks=len(result.get("splitter", {}).get("documents", [])),
                        confidentiality_level=confidentiality,
                        embedding=embedding,
                        meta_data={
                            "mime_type": mime_type,
                            "modified_time": file_metadata.get("modifiedTime"),
                            "size": file_metadata.get("size"),
                            "document_type": document_type,
                        },
                    )

                    # Merge or add
                    await session.merge(db_doc)
                    chunks_created += 1

                await session.commit()

            # Invalidate cache
            await cache_manager.invalidate_pattern(f"doc:{file_id}:*")

            logger.info(f"Indexed file {file_id}: {chunks_created} chunks created (type: {document_type})")

            return {
                "file_id": file_id,
                "chunks_created": chunks_created,
                "document_type": document_type,
                "status": "success",
            }

        except Exception as e:
            logger.error(f"Failed to index file {file_id}: {e}")
            raise

    def _detect_confidentiality(self, text: str) -> str:
        """Detect confidentiality level using pattern matching."""
        if not settings.rag_enable_confidentiality_filter:
            return settings.rag_default_confidentiality

        text_lower = text.lower()

        # High confidentiality patterns
        high_patterns = [
            "confidential",
            "secret",
            "private",
            "password",
            "api key",
            "access token",
            "credential",
            "ssn",
            "social security",
        ]

        # Medium confidentiality patterns
        medium_patterns = ["internal", "restricted", "proprietary", "sensitive"]

        for pattern in high_patterns:
            if pattern in text_lower:
                return "high"

        for pattern in medium_patterns:
            if pattern in text_lower:
                return "medium"

        return "low"


# Singleton instance
indexing_pipeline = IndexingPipeline()
