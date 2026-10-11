"""Real loopback TLS handshake; this is a local transport test, not a real Freebox."""

import asyncio
import datetime
import ssl

import aiohttp
import pytest
from aiohttp import web
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from custom_components.freebox_ultra_ultimate.api import ApiVersion, FreeboxClient, FreeboxError


@pytest.mark.enable_socket
async def test_real_aiohttp_tls_enforces_hostname(tmp_path):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.fbxos.fr")])
    now = datetime.datetime.now(datetime.UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("example.fbxos.fr")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = tmp_path / "cert.pem", tmp_path / "key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(cert_path, key_path)
    client_context = ssl.create_default_context(cafile=str(cert_path))
    app = web.Application()

    async def handler(request):
        assert request.headers["X-Fbx-App-Auth"] == "session-test"
        return web.json_response({"success": True, "result": {"uptime_val": 42}})

    app.router.add_get("/api/v12/system/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    try:
        async with aiohttp.ClientSession() as session:
            client = FreeboxClient(session, client_context, "127.0.0.1", port)
            client._session_token = "session-test"
            client.version = ApiVersion.parse(
                {"uid": "tls-test", "api_version": "12.0", "api_domain": "example.fbxos.fr"}
            )
            assert await client.get("system/") == {"uptime_val": 42}
            client.version = ApiVersion.parse(
                {"uid": "tls-test", "api_version": "12.0", "api_domain": "wrong.fbxos.fr"}
            )
            loop = asyncio.get_running_loop()
            handler_before = loop.get_exception_handler()

            def expected_tls_rejection(loop, context):
                # A client rejecting the server name resets the accepted server socket.
                if (
                    isinstance(context.get("exception"), ConnectionResetError)
                    and context.get("message") == "Error on transport creation for incoming connection"
                ):
                    return
                if handler_before:
                    handler_before(loop, context)
                else:
                    loop.default_exception_handler(context)

            loop.set_exception_handler(expected_tls_rejection)
            try:
                with pytest.raises(FreeboxError, match="tls_certificate_error"):
                    await client.get("system/")
                await asyncio.sleep(0.1)
            finally:
                loop.set_exception_handler(handler_before)
    finally:
        await runner.cleanup()


@pytest.mark.enable_socket
@pytest.mark.parametrize("case", ["legacy_valid", "wrong_hostname", "untrusted_ca", "expired", "bad_signature"])
async def test_legacy_chain_preserves_tls_identity_and_trust(tmp_path, case):
    from custom_components.freebox_ultra_ultimate.api import tls_context

    root_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    root_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Test Legacy Root")])
    leaf_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.fbxos.fr")])
    now = datetime.datetime.now(datetime.UTC)
    root = (
        x509.CertificateBuilder()
        .subject_name(root_name)
        .issuer_name(root_name)
        .public_key(root_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=10))
        .not_valid_after(now + datetime.timedelta(days=10))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(root_key.public_key()), critical=False)
        .add_extension(x509.KeyUsage(False, False, False, False, False, True, True, False, False), critical=True)
        .sign(root_key, hashes.SHA256())
    )
    signing_key = (
        rsa.generate_private_key(public_exponent=65537, key_size=2048) if case == "bad_signature" else root_key
    )
    # Deliberately omit AuthorityKeyIdentifier: reproduce the Freebox chain incompatibility.
    leaf = (
        x509.CertificateBuilder()
        .subject_name(leaf_name)
        .issuer_name(root_name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=2))
        .not_valid_after(now + datetime.timedelta(days=-1 if case == "expired" else 1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("example.fbxos.fr")]), critical=False)
        .sign(signing_key, hashes.SHA256())
    )
    root_file, chain_file, key_file = tmp_path / "root.pem", tmp_path / "chain.pem", tmp_path / "key.pem"
    root_file.write_bytes(root.public_bytes(serialization.Encoding.PEM))
    chain_file.write_bytes(
        leaf.public_bytes(serialization.Encoding.PEM) + root.public_bytes(serialization.Encoding.PEM)
    )
    key_file.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_context.load_cert_chain(chain_file, key_file)
    app = web.Application()

    async def handler(request):
        return web.json_response({"success": True, "result": {"uptime_val": 42}})

    app.router.add_get("/api/v16/system/", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0, ssl_context=server_context)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()

    def expected_rejection(loop, context):
        if (
            isinstance(context.get("exception"), ConnectionResetError)
            and context.get("message") == "Error on transport creation for incoming connection"
        ):
            return
        if original_handler:
            original_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    loop.set_exception_handler(expected_rejection)
    try:
        context = tls_context()
        if case != "untrusted_ca":
            context.load_verify_locations(cafile=str(root_file))
        async with aiohttp.ClientSession() as session:
            client = FreeboxClient(session, context, "127.0.0.1", port)
            client._session_token = "session-test"
            client.version = ApiVersion.parse(
                {
                    "uid": "tls-test",
                    "api_version": "16.0",
                    "api_domain": "wrong.fbxos.fr" if case == "wrong_hostname" else "example.fbxos.fr",
                }
            )
            if case == "legacy_valid":
                strict = ssl.create_default_context(cafile=str(root_file))
                strict.verify_flags |= ssl.VERIFY_X509_STRICT
                client.context = strict
                with pytest.raises(FreeboxError, match="tls_certificate_error"):
                    await client.get("system/")
                client.context = context
                assert await client.get("system/") == {"uptime_val": 42}
            else:
                with pytest.raises(FreeboxError, match="tls_certificate_error"):
                    await client.get("system/")
            await asyncio.sleep(0.1)
    finally:
        await runner.cleanup()
        loop.set_exception_handler(original_handler)
