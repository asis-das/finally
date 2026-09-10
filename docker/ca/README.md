# Corporate CA certificates

Drop any corporate root/intermediate CA certificates here as `*.crt` files
(PEM-encoded, despite the extension) if your network uses a TLS-intercepting
proxy. They are installed into the system trust store in **both** Docker build
stages, so `npm`, `next/font`, `pip`/`uv` and LiteLLM all keep working *with
certificate verification enabled*.

This directory is intentionally never empty — the Dockerfile `COPY`s it
unconditionally, and an empty glob would fail the build.

To export the Windows root store to a PEM (PowerShell):

    Get-ChildItem Cert:\LocalMachine\Root, Cert:\LocalMachine\CA |
      ForEach-Object {
        "-----BEGIN CERTIFICATE-----"
        [Convert]::ToBase64String($_.RawData, 'InsertLineBreaks')
        "-----END CERTIFICATE-----"
      } | Set-Content -Encoding ascii docker/ca/corporate.crt

Never disable verification instead (`NODE_TLS_REJECT_UNAUTHORIZED=0`,
`PYTHONHTTPSVERIFY=0`, `--no-check-certificate`). A documented gap beats a
silently insecure image.
