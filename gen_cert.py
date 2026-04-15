import ipaddress
import os
from datetime import datetime, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization


def parse_san_entries(raw_hosts: str) -> list[x509.GeneralName]:
    entries: list[x509.GeneralName] = []
    for host in [item.strip() for item in raw_hosts.split(",") if item.strip()]:
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            entries.append(x509.DNSName(host))
    return entries

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
with open("server.key", "wb") as f:
    f.write(key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    ))

subject = issuer = x509.Name([
    x509.NameAttribute(NameOID.ORGANIZATION_NAME, u"CN MiniProject")
])
san_hosts = os.getenv("CHAT_TLS_HOSTS", "localhost,127.0.0.1")
cert = x509.CertificateBuilder().subject_name(
    subject
).issuer_name(
    issuer
).public_key(
    key.public_key()
).serial_number(
    x509.random_serial_number()
).not_valid_before(
    datetime.utcnow() - timedelta(days=1)
).not_valid_after(
    datetime.utcnow() + timedelta(days=365)
).add_extension(
    x509.SubjectAlternativeName(parse_san_entries(san_hosts)),
    critical=False,
).sign(key, hashes.SHA256())

with open("server.crt", "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))
print("Certificates generated successfully")
