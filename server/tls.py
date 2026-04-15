import os
import ssl
from pathlib import Path


DEFAULT_CERT_PATH = Path(os.getenv("CHAT_TLS_CERT", "server.crt"))
DEFAULT_KEY_PATH = Path(os.getenv("CHAT_TLS_KEY", "server.key"))


def create_server_ssl_context(
    cert_path: Path | str = DEFAULT_CERT_PATH,
    key_path: Path | str = DEFAULT_KEY_PATH,
) -> ssl.SSLContext:
    cert_file = Path(cert_path)
    key_file = Path(key_path)
    if not cert_file.exists() or not key_file.exists():
        raise FileNotFoundError(
            f"Missing TLS materials: {cert_file} and {key_file}. Run gen_cert.py first."
        )

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_file), str(key_file))
    return context


def create_client_ssl_context(cert_path: Path | str = DEFAULT_CERT_PATH) -> ssl.SSLContext:
    cert_file = Path(cert_path)
    if cert_file.exists():
        context = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(cert_file))
        context.check_hostname = True
        return context

    return ssl._create_unverified_context()