"""Google Drive integration for document ingestion."""
import io
import json
import logging
import mimetypes
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import pypdf
from docx import Document as DocxDocument

from app.core.config import settings

logger = logging.getLogger(__name__)


class GoogleDriveService:
    """Service for fetching documents from Google Drive."""

    SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

    def __init__(self):
        self.service = None
        self.folder_id = settings.google_drive_folder_id

    def authenticate(self):
        """Authenticate with Google Drive API."""
        if self.service is not None:
            return

        try:
            # Try to parse as JSON string first (from environment variable)
            try:
                service_account_info = json.loads(settings.google_service_account_json)
                credentials = service_account.Credentials.from_service_account_info(
                    service_account_info,
                    scopes=self.SCOPES,
                )
                logger.info("Loaded Google service account from JSON string")
            except (json.JSONDecodeError, ValueError, TypeError):
                # Fall back to file path
                creds_file = Path(settings.google_service_account_json)
                if not creds_file.exists():
                    raise FileNotFoundError(
                        f"Service account file not found: {creds_file}. "
                        "Please add your google-service-account.json file or set GOOGLE_SERVICE_ACCOUNT_JSON env var."
                    )

                credentials = service_account.Credentials.from_service_account_file(
                    str(creds_file),
                    scopes=self.SCOPES,
                )
                logger.info("Loaded Google service account from file")

            self.service = build("drive", "v3", credentials=credentials)
            logger.info("Authenticated with Google Drive API successfully")
        except Exception as e:
            logger.error(f"Failed to authenticate with Google Drive: {e}")
            raise

    def list_files(
        self,
        folder_id: str = None,
        mime_types: List[str] = None,
        modified_after: datetime = None,
    ) -> List[Dict[str, Any]]:
        """List files in a Google Drive folder."""
        self.authenticate()

        folder_id = folder_id or self.folder_id
        mime_types = mime_types or settings.rag_supported_mimetypes

        try:
            # Build query
            query_parts = [f"'{folder_id}' in parents", "trashed=false"]

            if mime_types:
                mime_query = " or ".join([f"mimeType='{mt}'" for mt in mime_types])
                query_parts.append(f"({mime_query})")

            if modified_after:
                timestamp = modified_after.isoformat() + "Z"
                query_parts.append(f"modifiedTime > '{timestamp}'")

            query = " and ".join(query_parts)

            # Fetch files
            results = []
            page_token = None

            while True:
                response = (
                    self.service.files()
                    .list(
                        q=query,
                        spaces="drive",
                        fields="nextPageToken, files(id, name, mimeType, size, modifiedTime, parents)",
                        pageToken=page_token,
                        pageSize=100,
                    )
                    .execute()
                )

                files = response.get("files", [])
                results.extend(files)

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            logger.info(f"Found {len(results)} files in Google Drive folder")
            return results

        except Exception as e:
            logger.error(f"Failed to list Google Drive files: {e}")
            raise

    def get_changed_files(self) -> List[Dict[str, Any]]:
        """
        Files to consider for incremental refresh.

        Currently lists the same corpus as list_files(); Drive change notifications
        can refine this later.
        """
        return self.list_files()

    def download_file(self, file_id: str, mime_type: str) -> Optional[bytes]:
        """Download file content from Google Drive."""
        self.authenticate()

        try:
            # Google Docs need to be exported
            if mime_type.startswith("application/vnd.google-apps"):
                if "document" in mime_type:
                    export_mime = "text/plain"
                elif "spreadsheet" in mime_type:
                    export_mime = "text/csv"
                elif "presentation" in mime_type:
                    export_mime = "text/plain"
                else:
                    logger.warning(f"Unsupported Google Workspace type: {mime_type}")
                    return None

                request = self.service.files().export_media(fileId=file_id, mimeType=export_mime)
            else:
                request = self.service.files().get_media(fileId=file_id)

            # Download
            file_handle = io.BytesIO()
            downloader = MediaIoBaseDownload(file_handle, request)

            done = False
            while not done:
                status, done = downloader.next_chunk()

            content = file_handle.getvalue()
            logger.debug(f"Downloaded file {file_id} ({len(content)} bytes)")
            return content

        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            return None

    def extract_text(self, content: bytes, mime_type: str, filename: str = "") -> str:
        """Extract text from file content based on MIME type."""
        try:
            # Plain text
            if mime_type == "text/plain" or mime_type.startswith("text/"):
                return content.decode("utf-8", errors="ignore")

            # PDF
            elif mime_type == "application/pdf":
                pdf_file = io.BytesIO(content)
                reader = pypdf.PdfReader(pdf_file)
                text_parts = []
                for page in reader.pages:
                    text_parts.append(page.extract_text())
                return "\n\n".join(text_parts)

            # DOCX
            elif mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                doc_file = io.BytesIO(content)
                doc = DocxDocument(doc_file)
                paragraphs = [p.text for p in doc.paragraphs]
                return "\n\n".join(paragraphs)

            # Markdown
            elif mime_type == "text/markdown" or filename.endswith(".md"):
                return content.decode("utf-8", errors="ignore")

            else:
                logger.warning(f"Unsupported MIME type for text extraction: {mime_type}")
                return ""

        except Exception as e:
            logger.error(f"Failed to extract text from {mime_type}: {e}")
            return ""

    def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get metadata for a specific file."""
        self.authenticate()

        try:
            file_meta = (
                self.service.files()
                .get(
                    fileId=file_id,
                    fields="id, name, mimeType, size, modifiedTime, createdTime, parents",
                )
                .execute()
            )
            return file_meta
        except Exception as e:
            logger.error(f"Failed to get file metadata for {file_id}: {e}")
            return None


# Global Google Drive service instance
gdrive_service = GoogleDriveService()
