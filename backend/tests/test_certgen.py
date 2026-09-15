import ssl
import tempfile
from pathlib import Path

from cryptography import x509

from app import certgen


def test_build_certificate_includes_required_and_custom_sans():
    cert_pem, key_pem, cert_der = certgen.build_certificate(["10.97.15.58", "sqlcheck-host"])
    cert = x509.load_pem_x509_certificate(cert_pem)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    ip_names = [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    dns_names = san.get_values_for_type(x509.DNSName)

    assert "127.0.0.1" in ip_names
    assert "10.97.15.58" in ip_names
    assert "localhost" in dns_names
    assert "sqlcheck-host" in dns_names

    # DER round-trips to the same certificate.
    der_cert = x509.load_der_x509_certificate(cert_der)
    assert der_cert.serial_number == cert.serial_number


def test_generated_cert_and_key_load_into_an_ssl_context():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp)
        certgen.write_certificate(out_dir, ["10.97.15.58"], days=30)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        # Must not raise: proves the cert+key are a valid, matching pair.
        ctx.load_cert_chain(certfile=str(out_dir / "sqlcheck.crt"), keyfile=str(out_dir / "sqlcheck.key"))


def test_no_hosts_still_includes_required_sans():
    cert_pem, _key_pem, _der = certgen.build_certificate([])
    cert = x509.load_pem_x509_certificate(cert_pem)
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "127.0.0.1" in [str(ip) for ip in san.get_values_for_type(x509.IPAddress)]
    assert "localhost" in san.get_values_for_type(x509.DNSName)


def test_cli_main_writes_files_and_returns_zero():
    with tempfile.TemporaryDirectory() as tmp:
        out_dir = Path(tmp) / "certs"
        rc = certgen.main(["--out-dir", str(out_dir), "--host", "10.97.15.58", "--days", "10"])
        assert rc == 0
        assert (out_dir / "sqlcheck.crt").exists()
        assert (out_dir / "sqlcheck.key").exists()
        assert (out_dir / "sqlcheck.cer").exists()


def test_cli_main_returns_nonzero_on_failure():
    with tempfile.TemporaryDirectory() as tmp:
        # Point --out-dir at a path that is a *file*, not a directory, so
        # mkdir(parents=True) inside write_certificate must fail.
        blocking_file = Path(tmp) / "blocked"
        blocking_file.write_text("x")
        rc = certgen.main(["--out-dir", str(blocking_file / "certs")])
        assert rc == 1
