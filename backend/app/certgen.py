"""Self-signed TLS certificate generation for the production deploy
(user's explicit decision: HTTPS on port 443, self-signed, "at least 256
bits" — implemented as ECDSA P-384 + SHA-384, well past that bar).

Run as `python -m app.certgen --out-dir /certs --host <ip-or-name> [...]`.
Always includes `127.0.0.1` and `localhost` as SANs in addition to whatever
`--host` values are passed, regardless of the caller — the Dockerfile's own
HEALTHCHECK connects to `127.0.0.1:8000` and pins to this exact certificate
(see Dockerfile comment), so that SAN entry is load-bearing, not optional.
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import stat
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

REQUIRED_SAN_HOSTS = ("127.0.0.1", "localhost")


def _san_entry(host: str) -> x509.GeneralName:
    try:
        return x509.IPAddress(ipaddress.ip_address(host))
    except ValueError:
        return x509.DNSName(host)


def build_certificate(
    hosts: list[str], days: int = 825
) -> tuple[bytes, bytes, bytes]:
    """Returns (cert_pem, key_pem, cert_der) for a self-signed ECDSA P-384
    certificate covering every host in `hosts` plus the always-required
    loopback/localhost entries."""
    all_hosts = list(dict.fromkeys([*hosts, *REQUIRED_SAN_HOSTS]))  # de-dup, keep order
    san_names = [_san_entry(h) for h in all_hosts]

    key = ec.generate_private_key(ec.SECP384R1())

    common_name = hosts[0] if hosts else "SQLCheck 2.0"
    subject = issuer = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "SQLCheck 2.0 (self-signed)"),
        ]
    )

    now = datetime.now(UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))  # tolerate clock skew
        .not_valid_after(now + timedelta(days=days))
        .add_extension(x509.SubjectAlternativeName(san_names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=True,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
    )
    cert = builder.sign(key, hashes.SHA384())

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    cert_der = cert.public_bytes(serialization.Encoding.DER)
    key_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return cert_pem, key_pem, cert_der


def write_certificate(out_dir: Path, hosts: list[str], days: int) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cert_pem, key_pem, cert_der = build_certificate(hosts, days=days)

    crt_path = out_dir / "sqlcheck.crt"
    key_path = out_dir / "sqlcheck.key"
    cer_path = out_dir / "sqlcheck.cer"

    crt_path.write_bytes(cert_pem)
    key_path.write_bytes(key_pem)
    cer_path.write_bytes(cert_der)

    with contextlib.suppress(OSError):  # best-effort on Windows
        key_path.chmod(stat.S_IRUSR | stat.S_IWUSR)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate a self-signed HTTPS certificate for SQLCheck 2.0."
    )
    parser.add_argument("--out-dir", required=True, help="Directory to write sqlcheck.crt/.key/.cer into")
    parser.add_argument(
        "--host",
        action="append",
        default=[],
        help="SAN entry (IP or hostname); repeatable. 127.0.0.1/localhost are always included.",
    )
    parser.add_argument("--days", type=int, default=825, help="Validity period in days (default 825)")
    args = parser.parse_args(argv)

    try:
        write_certificate(Path(args.out_dir), args.host, args.days)
    except Exception as exc:  # noqa: BLE001 - CLI entrypoint: report, don't traceback-dump
        print(f"certgen 失敗：{exc}", file=sys.stderr)
        return 1

    print(f"已產生憑證於 {args.out_dir}（SAN: {', '.join([*args.host, *REQUIRED_SAN_HOSTS])}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
