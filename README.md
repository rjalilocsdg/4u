
## Build and run

Build on the same OS, CPU architecture, and CPython minor version as the deployment
target. Linux requires GCC, Python development headers, and binutils; macOS requires
Xcode command-line tools. Use CPython 3.13 or 3.14.

```sh
python3.13 -m venv .venv-native
.venv-native/bin/python -m pip install -r requirements-build.txt
.venv-native/bin/python tools/build_obfuscated.py
cd dist/native
../../.venv-native/bin/python run.py
```

Set `DATA_DIR` to a writable persistent directory, `ADMIN_PASSWORD` to your admin
password, and `SECRET_KEY` to a stable secret using your deployment environment.
`PORT` defaults to 8000. Existing Telegram and hosting environment settings apply.
On another host, install `requirements.txt` in its runtime environment first.
`python -m uvicorn main:app` also works from inside the release directory.

The release contains six native modules, a small launcher, runtime requirements,
and a SHA-256 manifest. It contains no application `.py`, `.pyc`, generated C, or
debug files. The manifest is an inventory for corruption checking, not a digital
signature. Intermediate source/C files live in a private temporary directory that
is cleaned up after the build; an interrupted or forcibly killed build can leave
temporary files, so keep build machines private. Existing output is never
overwritten; choose `--output dist/another-release` for a subsequent build.

Before publishing output, the build exercises native imports, async route
recognition, authentication, pages, VLESS header parsing, bandwidth throttling,
and persistence using temporary data and an in-process HTTP client. Telegram is
disabled for verification. Live relay/network interoperability still requires a
deployment test.

## Linux container

```sh
docker build -t x4g-native .
docker run --rm -p 8000:8000 -v x4g-data:/data \
  -e ADMIN_PASSWORD -e SECRET_KEY x4g-native
```

The final image copies only the verified release from the builder. Share the final
image, not build caches or builder layers; these contain intermediate sources.

## Limits

Native compilation raises the reverse-engineering cost, but does not make code
unrecoverable. Module/API names, runtime strings and HTML/JavaScript served to the
browser remain observable. Secrets belong in runtime configuration. Debugger
blocking and repeated encoding layers do not provide a security boundary.

Compiler compatibility settings follow the
[Cython compiler directive documentation](https://docs.cython.org/en/latest/src/userguide/source_files_and_compilation.html#compiler-directives).
