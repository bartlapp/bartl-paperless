from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from paperless_records_xml import extraction
from paperless_records_xml.extraction import XMLExtractionError, extract_bytes, extract_xml
from paperless_records_xml.parser import XMLDocumentParser, render_thumbnail


class XMLTests(unittest.TestCase):
    def test_invoice_namespaces_and_attributes(self):
        text = extract_bytes(b'''<?xml version="1.0" encoding="UTF-8"?>
<Invoice xmlns="urn:invoice" xmlns:a="urn:attribute">
  <ID a:scheme="test">INV-2026-001</ID>
  <Amount currencyID="EUR">123.45</Amount>
</Invoice>''')
        self.assertIn("Namespace ns1: urn:invoice", text)
        self.assertIn("Namespace ns2: urn:attribute", text)
        self.assertIn("ns1:Invoice/ns1:ID/@ns2:scheme: test", text)
        self.assertIn("ns1:Invoice/ns1:ID: INV-2026-001", text)
        self.assertIn("ns1:Invoice/ns1:Amount/@currencyID: EUR", text)
        self.assertIn("ns1:Invoice/ns1:Amount: 123.45", text)

    def test_encoding_boundaries(self):
        for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
            declaration = "UTF-8" if encoding == "utf-8" else "UTF-16"
            data = f'<?xml version="1.0" encoding="{declaration}"?><r>Grüße € 東京</r>'.encode(encoding)
            with self.subTest(encoding=encoding):
                self.assertIn("r: Grüße € 東京", extract_bytes(data))
        self.assertIn("r: Grüße", extract_bytes('<r>Grüße</r>'.encode("utf-8-sig")))

    def test_predefined_entities_and_mixed_text(self):
        text = extract_bytes(b'<r label="A &amp; B">before <b>bold</b> after &lt;end&gt;</r>')
        for value in ("A & B", "before", "bold", "after <end>"):
            self.assertIn(value, text)

    def test_malformed_and_invalid_encoding_are_rejected(self):
        for data in (b"", b"<r>", b"<r/><s/>", b"<r>\xff</r>", b'<r>&unknown;</r>',
                     b'<?xml version="1.0" encoding="unsupported"?><r/>'):
            with self.subTest(data=data), self.assertRaises(XMLExtractionError):
                extract_bytes(data)

    def test_dtd_entities_and_external_references_rejected_in_all_encodings(self):
        attacks = (
            '<!DOCTYPE r><r/>',
            '<!DOCTYPE r SYSTEM "http://127.0.0.1:9/private"><r/>',
            '<!DOCTYPE r [<!ENTITY x SYSTEM "file:///etc/passwd">]><r>&x;</r>',
            '<!DOCTYPE r [<!ENTITY x "expanded">]><r>&x;</r>',
            '<!DOCTYPE r [<!ENTITY % x SYSTEM "http://127.0.0.1:9/private">%x;]><r/>',
        )
        for attack in attacks:
            for encoding in ("utf-8", "utf-16", "utf-16-le", "utf-16-be"):
                data = ('<?xml version="1.0"?>' + attack).encode(encoding)
                with self.subTest(attack=attack, encoding=encoding), self.assertRaises(XMLExtractionError):
                    extract_bytes(data)

    def test_xinclude_and_stylesheets_are_inert(self):
        data = b'''<?xml-stylesheet type="text/xsl" href="http://127.0.0.1:9/style"?>
<r xmlns:xi="http://www.w3.org/2001/XInclude"><xi:include href="file:///etc/passwd"/></r>'''
        with patch("socket.socket", side_effect=AssertionError("network forbidden")):
            text = extract_bytes(data)
        self.assertIn("/@href: file:///etc/passwd", text)
        self.assertNotIn("root:x:", text)

    def test_resource_boundaries_reject_without_partial_output(self):
        cases = (("MAX_BYTES", 5, b"<root/>"),
                 ("MAX_DEPTH", 2, b"<r><a><b/></a></r>"),
                 ("MAX_ELEMENTS", 2, b"<r><a/><b/></r>"),
                 ("MAX_TEXT_CHARS", 5, b"<r>long content</r>"))
        for setting, limit, data in cases:
            with self.subTest(setting=setting), patch.object(extraction, setting, limit):
                with self.assertRaises(XMLExtractionError):
                    extract_bytes(data)

    def test_original_bytes_unchanged(self):
        data = '<?xml version="1.0"?><r a="€">Grüße</r>'.encode("utf-16")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "invoice.xml"
            path.write_bytes(data)
            self.assertIn("Grüße", extract_xml(path))
            self.assertEqual(path.read_bytes(), data)
            self.assertEqual(list(Path(directory).iterdir()), [path])

    def test_plugin_does_not_offer_pdf_or_claim_other_formats(self):
        parser = XMLDocumentParser.__new__(XMLDocumentParser)
        self.assertFalse(parser.can_produce_archive)
        self.assertFalse(parser.requires_pdf_rendition)
        self.assertIsNone(parser.get_archive_path())
        self.assertIsNone(XMLDocumentParser.score("application/json", "invoice.xml"))
        self.assertEqual(XMLDocumentParser.score("application/xml", "invoice.xml"), 10)

    def test_real_thumbnail_pixels(self):
        from PIL import Image, ImageFont
        with tempfile.TemporaryDirectory() as directory:
            path = render_thumbnail("Invoice INV-001\nAmount EUR 123.45", Path(directory) / "thumb.webp", ImageFont.load_default())
            with Image.open(path) as image:
                self.assertEqual(image.format, "WEBP")
                self.assertEqual(image.size, (500, 700))
                self.assertLess(image.convert("L").getextrema()[0], 100)


if __name__ == "__main__":
    unittest.main()