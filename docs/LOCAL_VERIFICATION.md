# Campus Lost and Found local verification

Use Python 3.12 for the tested setup. The patched Pillow release requires Python 3.11 or later.

```sh
python -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

On Windows, use `.venv\Scripts\python.exe`. The local tests cover the Flask and SQLite workflow, including image validation and moderation. Azure support remains optional and separate. Use the [local launch and demo instructions](../README.md) and keep the local SQLite and uploaded test images under the ignored instance directory.

Set `DEMO_MODE=false` and configure deployment authentication and secret storage before exposing the app behind a reverse proxy. The automatic student demo is intended for loopback-only evaluation.
