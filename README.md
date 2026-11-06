# Campus Hub · Lost & Found

A local-first campus service for reporting misplaced belongings, verifying ownership privately, and recording successful reunions. Built with Python, Flask, Jinja2, vanilla JavaScript, Bootstrap 5 (vendored locally), Flask-SQLAlchemy and SQLite. No Node build, cloud account or hosted frontend dependencies.

## No-signup demonstration

Local demo mode is enabled by default (`DEMO_MODE=true`). Open the app and you are automatically given a fictional student workspace; no registration or password is required. Use **Try staff workspace** in the banner to review claims, approve them and record handovers. **Switch to student** restores your original reporting history. Demo identities persist in that browser session. Use the seeded found reports to submit student claims, then switch to staff to review them. For an empty database, report a found item in a second browser session and claim it in the first.

Demo account creation and role switching are available only from loopback (127.0.0.1 / ::1). Set `DEMO_MODE=false` before any shared or deployed use, especially behind a local reverse proxy. With demo mode disabled, normal login, registration and staff CLI authorization apply. Azure actions still require real user-supplied credentials; they are never simulated.

## Run locally

Requires Python 3.10+ with pip. In this directory, run:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Generate a secret and put the printed value in .env as SECRET_KEY:
.venv\Scripts\python -c "import secrets; print(secrets.token_hex(32))"
# Optional: create a real staff login when demo mode is disabled
.venv\Scripts\python -m flask --app app:create_app create-staff
.venv\Scripts\python -m flask --app app:create_app seed-demo
.venv\Scripts\python -m flask --app app:create_app run
```

Open http://127.0.0.1:5000. The database and uploads initialize automatically inside `instance/`. On macOS/Linux substitute `.venv/bin/python`. `python app.py` is also supported. Restart after changing configuration. The app works offline once dependencies are installed; Bootstrap and all other UI assets are local.

The staff command prompts for a name, email and hidden password (12+ characters). There is no hardcoded staff password. The idempotent demo command creates 12 fictional reports, three students, two pending claims, a returned item and activity logs. It prints a randomly generated temporary student password once; use the printed Maya account for the demonstration. The fictional historical desk actor has an unknown random password; create your own staff account with the CLI. Reset a demonstration by stopping the server and removing `instance/campus.db` and unused uploads, then reseed. Never do this to production data.

```powershell
.venv\Scripts\python -m pytest -q
```

Tests use temporary isolated SQLite databases, real CSRF tokens and Flask's test client. They cover registration/login, role escalation prevention, staff access, report creation/filtering/ownership, image validation, private claims, competing approvals, handover, moderation, local-only operation, seeding and the staff CLI. No live Azure service is used.

## Features and roles

- Students register, sign in, create/edit their own open reports, upload photographs, search/filter, submit private ownership evidence, track claims and update their display name.
- Everyone can browse public report metadata. Signed-in users can see photographs. Evidence and claimant contact details are available only in the staff workspace; each student sees only their own claim status.
- Staff review evidence, approve/reject claims, record dated handovers and notes, hide/restore open reports, and inspect analytics and the activity trail. Approving a claim rejects remaining pending claims on the item.
- Analytics query the database for lost/found totals, pending claims, returns, categories, locations and report dates. Hidden reports are excluded from public statistics.
- Search supports keywords, category, type, exact location, status and oldest/newest event dates. Public results paginate at 12 items.

## Architecture

`app.py` is the application factory, session authentication, route authorization, forms and CLI. `models.py` defines the relational schema. `services.py` contains image processing, approval and aggregate queries. `azure_integration.py` isolates optional network code. Reusable Jinja templates render the interface; CSS and JavaScript need no build system. The motion system adapts the earlier PhishGuard scroll reveals: staggered entrances, a gently floating illustration, pointer parallax and hover feedback. CSS and the Web Animations API honor reduced-motion preferences without external animation libraries.

```mermaid
flowchart LR
    Browser[Browser: local Bootstrap + vanilla JS] -->|HTTP forms + CSRF| Flask[Flask + Jinja + sessions]
    Flask --> ORM[SQLAlchemy]
    ORM --> SQLite[(SQLite default)]
    ORM -. startup DATABASE_URL .-> SQL[(Optional Azure SQL)]
    Flask --> Files[Protected local photographs]
    Flask -. explicit user request + ephemeral SAS .-> Blob[Optional private Azure Blob container]
```

```mermaid
erDiagram
    USER ||--o{ LISTING : reports
    USER ||--o{ CLAIM : submits
    LISTING ||--o{ CLAIM : receives
    LISTING ||--o| HANDOVER : closes
    CLAIM ||--o| HANDOVER : verifies
    USER ||--o{ HANDOVER : records
    USER ||--o{ ACTIVITY_LOG : performs
    USER {
        int id PK
        string email UK
        string password_hash
        string role
    }
    LISTING {
        int id PK
        int user_id FK
        string kind
        string category
        string status
        date event_date
    }
    CLAIM {
        int id PK
        int listing_id FK
        int user_id FK
        text explanation
        string status
    }
    HANDOVER {
        int id PK
        int listing_id FK,UK
        int claim_id FK,UK
        int staff_id FK
        date date
        text notes
    }
    ACTIVITY_LOG {
        int id PK
        int actor_id FK
        string action
        string record
        datetime timestamp
    }
```

Users have many reports and claims. A unique `(listing_id, user_id)` pair prevents repeated claims. Handovers reference one unique listing and one unique approved claim. Listing/claim states and roles have CHECK constraints; foreign keys are enforced on SQLite and SQL Server. Indexed search/filter columns support browsing. UTC timestamps track creation and modification. Activity records use a human-readable record reference so they can represent several record types; this reference is not a foreign key.

Only one staff approval can claim an open listing: a conditional SQL UPDATE changes `open` to `claimed` and checks the affected-row count within the transaction. Competing approvals cannot both succeed. Claim changes, rejected competitors, and the audit entry commit together. Unique handover constraints prevent duplicate collection. This invariant is enforced by the application transaction, not a provider-specific filtered index; direct database administrators must preserve it.

## Optional Azure Blob lab

For Blob Storage only, run `python -m pip install azure-storage-blob` and restart Flask. Alternatively, install `requirements-azure.txt` if you also need the optional SQL driver. The credential fields remain visible and editable even without the SDK; connection buttons explain the required setup. The form offers token show/hide and Clear fields, and never restores a token after navigation. All cloud actions remain disabled gracefully when the Blob SDK is absent. The whole application works without Azure. The lab does not contact Azure on GET, login or startup. Each POST either tests a connection or copies an existing photograph belonging to the current user. Local storage remains authoritative and survives cloud failure.

1. Create an Azure Storage account and an existing **private** container outside this application. Do not enable anonymous blob access.
2. Generate a **container-scoped SAS** with HTTPS-only access and expiry within 24 hours. Use **read** to test container properties, **read plus create/write** for unique image uploads. Do not grant delete, list or administrative permissions. Prefer a user-delegation SAS where available.
3. Enter account name, container name and token in the authenticated Integration Lab. Test privacy with a read-scoped SAS before copying. Select one of your own uploaded photos for a copy operation. Every operation verifies private container properties before proceeding; upload-only SAS tokens are rejected.
4. Credentials are processed once and discarded. Re-enter for later requests. Clear/disconnect empties the form and returns to a disconnected state; there is no persistent connection or background syncing. The lab shows the most recent request result, not continuous health.

Only `https://<validated-account>.blob.core.windows.net` destinations are constructed. The token is never stored in SQLite, cookies, localStorage, HTML, client scripts or application logs. SDK errors are replaced with generic messages. Disable HTTP body/URL tracing in reverse proxies and Azure diagnostics that could capture SAS credentials; TLS is required for deployed forms. Never paste master account keys. The app does not provision resources, make containers public, or provide remote image serving. Repeated copies may fail because overwrites are deliberately disabled.

SDK references: [Microsoft Python Blob guide](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-python-get-started), [upload documentation](https://learn.microsoft.com/en-us/azure/storage/blobs/storage-blob-upload-python). Live connectivity, SAS permissions and Azure SQL have not been tested without user credentials.

## Optional Azure SQL

Azure SQL is server configuration, never student input. Install Microsoft **ODBC Driver 18 for SQL Server** on the host, then `pip install -r requirements-azure.txt`. Configure the firewall/private network and a database principal with only the required privileges. In the server's environment or private `.env`, set:

```text
DATABASE_URL=mssql+pyodbc://USERNAME:URL_ENCODED_PASSWORD@SERVER.database.windows.net:1433/DATABASE?driver=ODBC+Driver+18+for+SQL+Server&Encrypt=yes&TrustServerCertificate=no
```

URL-encode credentials; do not commit connection strings. Restart the application. SQLAlchemy initializes these same tables on startup; the database must already exist. Use a temporary schema-creation identity for setup, then a restricted runtime identity. The lab reports SQL Server configuration without disclosing credentials. This is startup provider selection, not live switching, synchronization, migration or a guarantee of network health. Back up and migrate data separately. A misconfigured cloud `DATABASE_URL` fails startup; unset it to use SQLite.

## Security and deployment considerations

Passwords use Werkzeug's salted hashing. Every mutating browser form uses a cryptographic, session-bound CSRF token checked server-side. Role and ownership checks protect routes. Session cookies are HTTP-only, SameSite Lax, expire after eight hours, and rotate on login. Jinja escapes input. Parameterized ORM queries and escaped LIKE wildcards protect searches. CSP blocks inline/third-party scripts and framing. Uploads have a 5 MB request limit, decoded-image validation, 16 MP pixel cap, JPEG re-encoding to discard source metadata, random names, and authenticated serving outside static assets. No user-supplied filenames are used on disk.

Set a stable random `SECRET_KEY` before deployment; absent a configured key, a random ephemeral development key invalidates sessions on restart. Set `COOKIE_SECURE=true` behind HTTPS. Do not use `flask --debug` on a deployed server. Use a production WSGI server (for example Waitress on Windows), TLS reverse proxy, restricted filesystem permissions and backups of database + uploads. Never commit `.env`, uploaded photos, database files or generated accounts. No unrestricted production debugger is enabled.

MVP boundaries: no email verification, password reset, MFA, login throttling, malware scanning, automatic matching, notifications or pagination of private dashboards. Add login throttling and account recovery before opening the service beyond a controlled academic demo. Staff views cap at 200 latest claims/reports and 100 log entries. Replaced photos remain on disk for safe manual maintenance. Schema migrations are intentionally out of scope. Do not put secrets in public report descriptions. Handover notes remain database records; the UI records them but does not provide a separate handover-history editor.

## Academic concepts demonstrated

**DBMS:** normalized relational entities, primary/foreign/unique keys, CHECK constraints, one-to-many relationships, indexed queries, aggregate GROUP BY analytics and transactional consistency. Conditional updates solve the competing-approval problem; unique constraints prevent duplicate claims and handovers.

**System design:** simple layered monolith, server rendering, request/session boundaries, authorization, pagination, bounded uploads, local storage lifecycle, audit trails, deterministic state transitions and graceful optional-dependency failure.

**DP-900:** structured transactional relational data versus unstructured blob photographs, OLTP application queries versus grouped descriptive analytics, local SQLite versus managed Azure SQL, and the distinction between storage and database services.

**Cloud security:** least privilege, time-bound delegated credentials, secret minimization, HTTPS, private containers, destination validation, server-side configuration, defense in depth and retaining local availability when cloud services fail. This project demonstrates concepts; it does not constitute certification or a hardened production service.




