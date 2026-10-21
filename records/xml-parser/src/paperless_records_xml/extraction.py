"""Bounded XML extraction. No stylesheet, schema, XInclude or URL resolution."""
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from xml.etree.ElementTree import ParseError

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

MAX_BYTES = 16 * 1024 * 1024
MAX_DEPTH = 128
MAX_ELEMENTS = 100_000
MAX_TEXT_CHARS = 32 * 1024 * 1024


class XMLExtractionError(ValueError):
    """Invalid, unsafe or over-limit XML; never partial ingestion."""


def extract_xml(document_path: Path) -> str:
    with document_path.open("rb") as source:
        data = source.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise XMLExtractionError("XML exceeds the 16 MiB input limit")
    return extract_bytes(data)


def extract_bytes(data: bytes) -> str:
    """Honor XML encoding declarations without replacement decoding."""
    if len(data) > MAX_BYTES:
        raise XMLExtractionError("XML exceeds the 16 MiB input limit")
    namespaces: dict[str, str] = {}
    path: list[str] = []
    lines: list[str] = []
    chars = 0
    count = 0

    def name(expanded: str) -> str:
        if not expanded.startswith("{"):
            return expanded
        uri, local = expanded[1:].split("}", 1)
        prefix = namespaces.setdefault(uri, f"ns{len(namespaces) + 1}")
        return f"{prefix}:{local}"

    def emit(label: str, value: str) -> None:
        nonlocal chars
        value = " ".join(value.split())
        if value:
            line = f"{label}: {value}"
            chars += len(line) + 1
            if chars > MAX_TEXT_CHARS:
                raise XMLExtractionError("XML exceeds the extracted text limit")
            lines.append(line)

    try:
        events = ElementTree.iterparse(
            BytesIO(data), events=("start", "end"),
            forbid_dtd=True, forbid_entities=True, forbid_external=True,
        )
        for event, element in events:
            if event == "start":
                count += 1
                if count > MAX_ELEMENTS:
                    raise XMLExtractionError("XML exceeds the element limit")
                path.append(name(element.tag))
                if len(path) > MAX_DEPTH:
                    raise XMLExtractionError("XML exceeds the nesting limit")
                label = "/".join(path)
                for key, value in element.attrib.items():
                    emit(f"{label}/@{name(key)}", value)
            else:
                label = "/".join(path)
                emit(label, element.text or "")
                path.pop()
                emit("/".join(path) + "/#tail", element.tail or "")
                element.clear()
    except (ParseError, DefusedXmlException, LookupError, UnicodeError) as error:
        raise XMLExtractionError(f"XML rejected: {error}") from error
    header = ["XML extracted content (original retained separately)"]
    header.extend(f"Namespace {prefix}: {uri}" for uri, prefix in namespaces.items())
    return "\n".join(header + lines)