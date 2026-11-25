# SPDX-License-Identifier: Apache-2.0
"""Run with the supported runtime's Requests/cryptography dependencies, no network service needed."""
import datetime
import http.server
import os
from pathlib import Path
import ssl
import tempfile
import threading
import unittest
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import requests


class ClientCATest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.root = Path(cls.directory.name)
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic client CA test")])
        now = datetime.datetime.now(datetime.timezone.utc)
        ca = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
              .public_key(key.public_key()).serial_number(x509.random_serial_number())
              .not_valid_before(now - datetime.timedelta(minutes=1))
              .not_valid_after(now + datetime.timedelta(days=1))
              .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
              .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
              .add_extension(x509.KeyUsage(digital_signature=False, content_commitment=False,
                             key_encipherment=False, data_encipherment=False, key_agreement=False,
                             key_cert_sign=True, crl_sign=True, encipher_only=False,
                             decipher_only=False), critical=True)
              .sign(key, hashes.SHA256()))
        leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        leaf = (x509.CertificateBuilder().subject_name(x509.Name([
                    x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
                .issuer_name(name).public_key(leaf_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(minutes=1))
                .not_valid_after(now + datetime.timedelta(days=1))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(key.public_key()), critical=False)
                .sign(key, hashes.SHA256()))
        cls.bundle = cls.root / "ca-bundle.pem"
        cls.bundle.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
        certificate = cls.root / "server.pem"
        certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
        private_key = cls.root / "server-key.pem"
        private_key.write_bytes(leaf_key.private_bytes(serialization.Encoding.PEM,
                               serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"verified")

            def do_POST(self):
                self.do_GET()

            def log_message(self, *args):
                pass

        cls.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, private_key)
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = f"https://localhost:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()
        cls.directory.cleanup()

    def request(self, method="GET", hostname="localhost"):
        # Mirror allauth's native requests.Session, without disabling TLS checks.
        with requests.Session() as session:
            return session.request(method, self.url.replace("localhost", hostname), timeout=5)

    def test_supplied_bundle_verifies_get_and_post(self):
        with patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": str(self.bundle), "NO_PROXY": "*"}, clear=True):
            for method in ("GET", "POST"):
                self.assertEqual(self.request(method).content, b"verified")

    def test_default_roots_do_not_trust_test_ca(self):
        with patch.dict(os.environ, {"NO_PROXY": "*"}, clear=True):
            with self.assertRaises(requests.exceptions.SSLError):
                self.request()

    def test_system_ca_variable_alone_does_not_configure_requests(self):
        with patch.dict(os.environ, {"SSL_CERT_FILE": str(self.bundle), "NO_PROXY": "*"}, clear=True):
            with self.assertRaises(requests.exceptions.SSLError):
                self.request()

    def test_bundle_does_not_disable_hostname_verification(self):
        with patch.dict(os.environ, {"REQUESTS_CA_BUNDLE": str(self.bundle), "NO_PROXY": "*"}, clear=True):
            with self.assertRaises(requests.exceptions.SSLError):
                self.request(hostname="127.0.0.1")

    def test_missing_and_invalid_bundles_fail(self):
        invalid = self.root / "invalid.pem"
        invalid.write_text("not a certificate")
        for path in (self.root / "missing.pem", invalid):
            with self.subTest(path=path), patch.dict(os.environ, {
                    "REQUESTS_CA_BUNDLE": str(path), "NO_PROXY": "*"}, clear=True):
                with self.assertRaises((OSError, requests.exceptions.SSLError)):
                    self.request()


if __name__ == "__main__":
    unittest.main()
