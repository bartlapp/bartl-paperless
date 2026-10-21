"""External parser for Paperless-ngx 3.3.0; originals stay native XML."""
from __future__ import annotations

import shutil
import tempfile
import textwrap
from pathlib import Path

from .extraction import XMLExtractionError, extract_xml


class XMLDocumentParser:
    name = "Records XML Parser"
    version = "1.0.0"
    author = "Florian Kessler GmbH"
    url = "https://fke.systems"
    uses_remote_service = False

    @classmethod
    def supported_mime_types(cls) -> dict[str, str]:
        return {"application/xml": ".xml", "text/xml": ".xml"}

    @classmethod
    def score(cls, mime_type: str, filename: str, path: Path | None = None) -> int | None:
        return 10 if mime_type in cls.supported_mime_types() else None

    @property
    def can_produce_archive(self) -> bool:
        return False

    @property
    def requires_pdf_rendition(self) -> bool:
        return False

    def __init__(self, logging_group: object = None) -> None:
        from django.conf import settings

        settings.SCRATCH_DIR.mkdir(parents=True, exist_ok=True)
        self._tempdir = Path(tempfile.mkdtemp(prefix="paperless-xml-", dir=settings.SCRATCH_DIR))
        self._text = ""

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        shutil.rmtree(self._tempdir, ignore_errors=True)

    def configure(self, context) -> None:
        # No source-context interpretation or remote processing.
        return None

    def parse(self, document_path: Path, mime_type: str, *, produce_archive: bool = True) -> None:
        from documents.parsers import ParseError

        self._text = ""
        if mime_type not in self.supported_mime_types():
            raise ParseError(f"Unsupported XML MIME type: {mime_type}")
        try:
            self._text = extract_xml(document_path)
        except (OSError, XMLExtractionError) as error:
            raise ParseError(str(error)) from error

    def get_text(self) -> str:
        return self._text

    def get_date(self):
        return None

    def get_archive_path(self) -> None:
        return None

    def get_page_count(self, document_path: Path, mime_type: str) -> None:
        return None

    def extract_metadata(self, document_path: Path, mime_type: str) -> list:
        # XML fields are in searchable content; no metadata-specific reparsing.
        return []

    def get_thumbnail(self, document_path: Path, mime_type: str) -> Path:
        from django.conf import settings
        from documents.parsers import ParseError
        from PIL import ImageFont

        try:
            font = ImageFont.truetype(settings.THUMBNAIL_FONT_NAME, 16, layout_engine=ImageFont.Layout.BASIC)
            return render_thumbnail(self._text, self._tempdir / "thumb.webp", font)
        except (OSError, ValueError) as error:
            raise ParseError(f"Cannot render XML thumbnail: {error}") from error


def render_thumbnail(text: str, output_path: Path, font) -> Path:
    """Render only a bounded first page; full extraction remains in Content."""
    from PIL import Image, ImageDraw

    image = Image.new("RGB", (500, 700), "white")
    draw = ImageDraw.Draw(image)
    rows = []
    for line in text[:100_000].splitlines():
        rows.extend(textwrap.wrap(line, width=48, replace_whitespace=True) or [""])
        if len(rows) >= 32:
            break
    draw.multiline_text((10, 10), "\n".join(rows[:32]), font=font, fill="black", spacing=4)
    image.save(output_path, format="WEBP")
    image.close()
    return output_path