# Private Psychotherapy Clinic — Full Reference

> Single consolidated documentation for the Private Clinic management system.
> Originally scattered across 11+ files; unified here for easy navigation.

---

## Table of Contents

1. [Overview](#1-overview)
2. [Quick Start](#2-quick-start)
3. [Features](#3-features)
4. [Architecture](#4-architecture)
5. [Development Guide](#5-development-guide)
6. [Testing](#6-testing)
7. [Design System](#7-design-system)
8. [Deployment](#8-deployment)
9. [Migration Guide (Beta → Production)](#9-migration-guide)
10. [Security Review](#10-security-review)
11. [Troubleshooting](#11-troubleshooting)
12. [Roadmap & Next Tasks](#12-roadmap--next-tasks)
13. [Changelog](#13-changelog)

---

## 1. Overview

A web application to manage patients, treatment notes, files, and receipts for a private psychotherapy clinic. Built with Flask + SQLite + Docker.

**Live site:** https://clinic.lior-clinic.org
**GitHub:** https://github.com/lioralo/Private_Clinic
**Stack:** Python / Flask / SQLite / Gunicorn / Caddy / Docker / AWS EC2 (il-central-1)

### Repository Structure

```
Private_Clinic/
├── app.py                  # Main Flask application
├── run.py                  # Alternative entry point
├── wsgi.py                 # WSGI entry for Gunicorn
├── clinic_app/             # Flask app package (blueprints + models)
│   ├── __init__.py
│   ├── models.py
│   ├── utils.py
│   └── routes/
│       ├── __init__.py
│       ├── auth.py
│       ├── calendar.py
│       ├── health.py
│       └── patients.py
├── templates/              # Jinja2 HTML templates (Hebrew RTL)
├── static/                 # CSS, JS, vendor assets, uploads
│   ├── style.css
│   ├── js/
│   ├── vendor/
│   └── uploads/
├── translations/           # Hebrew i18n (he.json)
├── scripts/                # Deployment & utility scripts
├── tests/                  # Unit tests
├── verification/           # Refactor guard & debug logs
├── docs/                   # Documentation
├── archive/                # Historical artifacts
├── patients_logs/          # Per-patient log files
├── AI S/                   # Design reference (React components)
├── .clinic_keys/           # Encrypted backup keys
├── secure_backups/         # Encrypted database backups
├── Dockerfile
├── docker-compose.prod.yml
├── Caddyfile               # Reverse proxy + TLS config
├── requirements.txt
├── schema.sql
└── .env.prod.example
```

---

## 2. Quick Start

### Prerequisites
- Python 3.11+
- pip

### Setup

```bash
git clone https://github.com/lioralo/Private_Clinic.git
cd Private_Clinic
pip install -r requirements.txt
python app.py
```

Open http://127.0.0.1:5000 in your browser.

### Environment Variables Required for Tests

```powershell
$env:SECRET_KEY = "test-secret-key-for-testing-12345"
$env:FLASK_ENV = "development"
$env:TESTING = "1"
```

For Google OAuth tests also set:
```powershell
$env:GOOGLE_OAUTH_CLIENT_ID = "test-client-id.apps.googleusercontent.com"
$env:GOOGLE_OAUTH_CLIENT_SECRET = "test-secret"
```

### CSRF Protection
CSRF protection is enabled. When running tests, ensure `WTF_CSRF_ENABLED` is set to `False` in the app config.

---

## 3. Features

### Patient CRM
- List patients by status: Ongoing, Candidate, Archived
- Full patient lifecycle (active/candidate/archived/deleted)
- Add / edit / view patient details with intake forms
- Patient search across all fields
- Patient detail export to DOCX
- Automatic next-appointment display in CRM table

### Calendar & Scheduling
- Weekly calendar view with FullCalendar
- Appointment CRUD (create / edit / delete from calendar)
- Recurring appointments (weekly, configurable per patient status)
- Blocked slots and vacancy management
- Conflict detection
- Public self-booking link with validation:
  - Name required, DOB optional
  - At least one contact method (phone or email)
  - Creates `waiting` status patient + one-time appointment + admin notification
- Cancel requests with admin review/approve/reject flow + email notification

### Group Therapy
- Group CRUD with archive/permanent-delete support
- Recurring group sessions (end by count or date)
- Session attendance tracking with member notes
- Session summaries with Google Docs sync
- Calendar links directly to group session records
- Three removal outcomes: remove from group, archive, or permanently delete

### Billing & Financial
- Service types management (admin UI)
- Auto-numbered receipts with line-item table
- PDF receipt generation (fpdf2)
- Revenue dashboard

### Messaging
- In-app threaded messaging between patients and admin
- Admin notification on public booking submission

### Patient Portal
- Patient dashboard with appointments, notes, treatment plans
- Past appointments view with shared notes toggle
- Treatment plan with goal tracking (interactive checkboxes)
- Session frequency chart
- Appointment cancel requests
- Change password

### Security
- Flask-Login authentication
- TOTP 2FA support
- Password reset flow
- Session revocation & inactivity timeout
- Rate limiting (DB-backed)
- Audit logging with security log viewer
- Role-based access (admin / patient)
- Clipboard restrictions for patients (copy/cut/paste blocked)

### Google Integration
- OAuth 2.0 connect/disconnect with PKCE
- Google Calendar sync (events push)
- Google Docs sync (pull/push session notes)
- Google Sheets (questionnaires)
- Manual sync and auto-sync
- Server-side integration state rendering

### Resource Library
- Shareable documents and links for patients
- Resource management (admin CRUD)

### Backup & Encryption
- Encrypted backup bundles with Fernet (AES-256)
- Backup scheduler with automatic rotation
- Restore with integrity verification
- Backup key management (.backup.key + env var)

### i18n / Hebrew Support
- Full Hebrew translations (685 keys, 100% coverage)
- Editable dictionary file at `translations/he.json`
- RTL layout with Bootstrap RTL
- Missing keys gracefully fall back to English

### Email Reminders
- Appointment email reminders
- SMTP configuration
- Cancel request email notifications

---

## 4. Architecture

### Monolith with Blueprint Refactor
The original `app.py` monolith is being progressively refactored into modular Flask blueprints under `clinic_app/routes/`.

**Refactored modules:**
- `clinic_app/routes/auth.py` — Authentication, registration, password reset
- `clinic_app/routes/calendar.py` — Calendar, appointments, slots (1050 lines)
- `clinic_app/routes/patients.py` — Patient CRUD, search
- `clinic_app/routes/health.py` — Health check endpoints

**Shared modules:**
- `clinic_app/utils.py` — Pure utility functions decoupled from app context (706 lines)
- `clinic_app/models.py` — DB helpers and model functions (11+ lines, cleaned of 200 lines of dead code)

**Refactor guard:** `verification/refactor_guard.py` snapshots route contracts and fails if routes are removed or HTTP methods change unexpectedly.

### Database
- SQLite (`clinic.db`)
- Schema defined in `schema.sql` with FK indexes on cancel_requests, schedules, slots
- Search indexes on patient name/email/phone
- Rate limiting table (`rate_limits`) — DB-backed instead of in-memory

---

## 5. Development Guide

### Running the App
```bash
pip install -r requirements.txt
python app.py
```

### Running Tests
```bash
python -m unittest discover -s tests -p 'test_*.py'
```

### Refactor Safety Checks
When splitting large modules (moving routes out of app.py), run the refactor guard:
```bash
# Snapshot baseline routes
python verification/refactor_guard.py snapshot

# Check route contract + smoke tests
python verification/refactor_guard.py check

# Shortcut wrapper
bash scripts/refactor_check.sh
```

### Google Calendar Notes
- OAuth callback accepts matching session state OR fresh signed fallback state (helps when proxy/browser drops session state)
- Token exchange forwards PKCE code verifier
- Appointment operations report sync failures to UI while saving local data
- Expired tokens are cleared; admin reconnects from Admin Profile page

### Hebrew i18n
- Edit `translations/he.json` to update translations without changing Python code
- Keys = English text, Values = Hebrew translations
- Missing keys fall back to built-in map, then to English

---

## 6. Testing

### Latest Full Regression
```bash
python -m unittest discover -s tests -p 'test_*.py'
```

### Test Files
| File | Scope |
|------|-------|
| `tests/test_app.py` | Core app functionality |
| `tests/test_security.py` | Auth, rate limiting, session security (37 tests) |
| `tests/test_google_oauth.py` | Google OAuth flow (28 tests) |
| `tests/test_google_calendar.py` | Google Calendar sync |
| `tests/test_google_docs.py` | Google Docs sync |
| `tests/test_google_docs_integration.py` | Docs integration (21 tests) |
| `tests/test_db.py` | Database operations |
| `tests/test_backup_db.py` | Backup/restore |
| `tests/test_export_data.py` | Data export |
| `tests/test_import_clinic_data.py` | Data import |
| `tests/test_patient_engagement.py` | Patient engagement |
| `tests/test_fix_calendar_times.py` | Calendar time fixes |
| `tests/test_refactor_guardrails.py` | Refactor guard |

### Test Counts (Latest)
- Full suite: 361+ tests passing
- Google OAuth: 28/28 pass
- Security: 37/37 pass
- Google Docs integration: 21/21 pass

---

## 7. Design System

### Color Palette
| Token | Color | Usage |
|-------|-------|-------|
| Primary | `#5676b6` (Blue) | Main brand color |
| Secondary | `#6c7792` (Gray-Blue) | Secondary actions |
| Tertiary | `#e3b453` (Amber/Gold) | Highlights |
| Background | `#f7f9fb` (Light Gray) | Page background |

### Typography
- **Headlines:** Manrope, Assistant (for Hebrew)
- **Body:** Inter, Assistant
- **Sizes:** Tailwind scale (text-sm, text-base, text-lg, etc.)

### Components
- **Buttons:** Primary color with rounded-xl
- **Cards:** bg-white, rounded-2xl, shadow-sm, border border-slate-100
- **Badges:** Rounded-full with appropriate background colors
- **Icons:** Material Symbols Outlined (preferred) or Bootstrap Icons

### Key Tailwind Classes
```
Colors:   text-primary, bg-primary, border-slate-100
Spacing:  gap-4, p-5, mb-6, px-4
Rounded:  rounded-lg, rounded-xl, rounded-2xl, rounded-full
Shadows:  shadow-sm
Font:     font-bold, font-semibold, text-slate-500
```

### Templates
- Base layout: `templates/layout.html` (Tailwind CSS color system)
- Styles: `static/style.css` (custom CSS variables + design tokens)
- Vendor: Bootstrap 5.3 RTL, Bootstrap Icons, FullCalendar, Tailwind CSS
- Design reference: `AI S/` (React components)

**Migration pattern** (Bootstrap → Tailwind):
```html
<!-- Before (Bootstrap) -->
<div class="card border-0 shadow-sm">
  <div class="card-header bg-white border-0">
    <h5 class="fw-bold mb-0">Title</h5>
  </div>
  <div class="card-body px-4 pb-4">Content...</div>
</div>

<!-- After (Tailwind) -->
<div class="bg-white rounded-2xl shadow-sm border border-slate-100">
  <div class="p-5 border-b border-slate-100">
    <h5 class="font-bold">Title</h5>
  </div>
  <div class="p-5">Content...</div>
</div>
```

---

## 8. Deployment

### Architecture
- Flask app served by Gunicorn (port 8000)
- Caddy reverse proxy with automatic TLS (Let's Encrypt)
- Docker Compose (app + caddy containers)
- Persistent data volume at `./data/`:
  - `clinic.db`
  - `uploads/`
  - `patients_logs/`
  - `app_log.txt`
  - `secure_backups/`
- AWS EC2 (il-central-1, t3.micro, 20 GiB gp3)

### Deployment Options

#### Option A: Automated Script (Recommended)
```bash
export SERVER_IP="13.61.60.244"
export SSH_KEY_PATH="/path/to/private-clinic-key.pem"
export DOMAIN="clinic.yourdomain.com"
bash scripts/deploy_with_verify.sh
```

#### Option B: Interactive
```bash
bash scripts/deploy_interactive.sh
```

#### Option C: Direct Docker Deploy
```bash
cp .env.prod.example .env.prod
# Edit .env.prod with DOMAIN, SECRET_KEY, BACKUP_ENCRYPTION_KEY
bash scripts/deploy_prod.sh
```

### 8-Step Deployment Verification

| Step | Purpose |
|------|---------|
| 1-2 | Verify local git state is clean |
| 3 | Create encrypted database backup |
| 4 | Setup and migrate AWS infrastructure |
| 5 | Deploy current local code |
| 6 | Verify remote commit matches local |
| 7 | Check containers are running |
| 8 | Review app logs for errors |
| 9 | Test HTTPS endpoints |

### Day-2 Operations

```bash
# Update app
git pull
docker compose --env-file .env.prod -f docker-compose.prod.yml up -d --build

# Deploy local checkout to AWS (without pushing to GitHub)
bash scripts/deploy_local_bundle_to_aws.sh \
  --ssh-target ubuntu@<server-ip> \
  --ssh-key /path/to/private-clinic-key.pem

# Restart
docker compose --env-file .env.prod -f docker-compose.prod.yml restart

# View logs
docker compose --env-file .env.prod -f docker-compose.prod.yml logs -f app
```

### EC2 Launch Checklist (il-central-1)
- AMI: Ubuntu Server 24.04 LTS
- Instance: t3.micro
- Storage: 20 GiB gp3
- Inbound ports: 22, 80, 443
- Elastic IP for stable address

### Generate Secure Values
```bash
python3 - <<'PY'
import secrets
from cryptography.fernet import Fernet
print('SECRET_KEY=' + secrets.token_urlsafe(64))
print('BACKUP_ENCRYPTION_KEY=' + Fernet.generate_key().decode())
PY
```

### Security Checklist
- Change default admin credentials immediately
- Keep `.env.prod` private
- Restrict SSH access to key auth only
- Enable UFW with ports 22, 80, 443
- Snapshot `./data` periodically

### Rollback
```bash
ssh -i key.pem ubuntu@IP
cd /opt/Private_Clinic
sudo docker compose down
# Restore from backup
python3 scripts/restore_db.py secure_backups/clinic_PREVIOUS.db.enc
sudo docker compose up -d
```

### Deployment Scripts Reference
| Script | Purpose |
|--------|---------|
| `scripts/deploy_with_verify.sh` | Full 8-step deployment with verification |
| `scripts/deploy_interactive.sh` | Deployment with prompts |
| `scripts/deploy_now.sh` | One-shot deployment |
| `scripts/deploy_prod.sh` | Direct Docker production deploy |
| `scripts/migrate_to_aws.sh` | AWS infrastructure setup |
| `scripts/deploy_local_bundle_to_aws.sh` | Deploy local checkout to AWS |
| `scripts/setup_ubuntu_docker.sh` | Install Docker on Ubuntu |
| `scripts/backup_db.py` | Encrypted database backup |
| `scripts/check_smtp.py` | SMTP configuration check |
| `scripts/verify_frontend.py` | Frontend verification |
| `scripts/refactor_check.sh` | Refactor guard wrapper |

---

## 9. Migration Guide

### Beta → Production Migration Runbook

**Estimated window:** 30-60 min (+ DNS propagation)
**Downtime:** ~5-15 min during Phase 4

### Phases

#### Phase 1: Pre-Migration Checklist
- Verify backup encryption key on beta
- Confirm admin credentials
- Run DB integrity check (`PRAGMA integrity_check`)
- Record row-count baseline
- Network connectivity validation

#### Phase 2: Beta Extraction
```bash
# Create encrypted backup
ssh ubuntu@<BETA_SERVER_IP>
cd /opt/private_clinic
curl -s -c /tmp/jar.txt -b /tmp/jar.txt -X POST \
  -d "username=ADMIN&password=PASS" \
  https://<BETA_DOMAIN>/login -o /dev/null
curl -s -b /tmp/jar.txt -X POST \
  https://<BETA_DOMAIN>/admin/backup_now
```

#### Phase 3: Data Transfer
- Transfer encrypted backup (`scp`)
- Transfer encryption key (`scp`, not email/Slack)
- Transfer uploads (`rsync -avz`)
- Transfer patient logs (`rsync -avz`)
- Transfer app log (optional)

#### Phase 4: Live Server Restoration
- Prepare env with beta encryption key
- Copy artifacts into data volume
- Stop Docker stack
- Restore DB from encrypted backup
- Bring stack back up
- Post-restore integrity check

#### Phase 5: Post-Migration Validation
- Data completeness (row counts)
- User authentication test
- Patient and appointment data checks
- Upload accessibility check
- Log integrity validation
- Backup health check

#### Phase 6: Operational Handoff
- Reset admin password
- Set up TOTP authenticator
- Rotate encryption key (recommended)
- Access control verification
- Set up monitoring alerts

### Troubleshooting (Migration)
| Symptom | Fix |
|---------|-----|
| `InvalidToken` during restore | BACKUP_ENCRYPTION_KEY mismatch between beta and live |
| Container exits after restore | Missing env var / DB permission issue |
| Integrity check fails | Restore from earlier backup file |
| Uploads 404 | Re-sync uploads, check UPLOAD_FOLDER path |
| TOTP codes rejected | Sync server clock (`timedatectl set-ntp true`) |

---

## 10. Security Review

### Scope
Application-level static review of auth/session/config/upload/public endpoints (2026-04-18).

### Findings

#### High
1. **Default Flask secret fallback** (`app.secret_key = os.environ.get('SECRET_KEY', 'dev')`)
   - Risk: Weak key in production compromises session integrity
   - Fix: Fail fast in non-testing when SECRET_KEY missing/weak

2. **Hard-coded admin bootstrap credentials** (`_seed_admin_user` in `app.py`)
   - Risk: Predictable credentials = account takeover
   - Fix: Require `DEFAULT_ADMIN_PASSWORD` env var, force password change on first boot

#### Medium
1. **Google Docs webhook trust model** — Validates X-Goog-Channel-ID only
   - Fix: Validate notification headers, store/verify channel metadata

2. **Public booking endpoints CSRF-exempt by design** (`/api/calendar/public/<token>/book`)
   - Fix: Added endpoint-level rate limiting (429 + Retry-After)

#### Low
1. **Missing secure cookie and hardening headers**
   - Fix: Added `SESSION_COOKIE_SECURE`, `SESSION_COOKIE_HTTPONLY`, `SESSION_COOKIE_SAMESITE`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, CSP

#### Implemented (2026-04-18)
- Public booking API rate limiting
- Response security headers + secure session cookie defaults
- Webhook required-header checks + optional secret verification
- Automated tests for above controls

### Fortinet TLS Inspection
Users behind Fortinet firewalls may see `ERR_CERT_AUTHORITY_INVALID`. This is network-level TLS inspection, not a server issue.

**Server-side:** Caddy serves public Let's Encrypt certificates correctly.
**Client-side:** Users install the enterprise Fortinet root CA in their OS trust store.

Verify:
```bash
curl -Iv https://<DOMAIN> 2>&1 | grep -i issuer
```
- Issuer showing "Let's Encrypt" = direct access OK
- Issuer showing "Fortinet" = network interception (install Fortinet CA)

---

## 11. Troubleshooting

### Deployment
| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| SSH connection fails | Wrong IP / key permissions | `chmod 600 key.pem`, check SG |
| Docker not running | `docker compose ps` | Check logs, restart services |
| HTTPS 404/502 | DNS / Caddy routing | `nslookup DOMAIN`, check Caddyfile |
| Cert errors | Fortinet / misconfig | Run `curl -Iv`, install CA or whitelist |

### App
| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Google Calendar not showing | OAuth expired | Reconnect from Admin Profile |
| Booking edit doesn't save | JS console error | Hard refresh (Ctrl+Shift+F5) |
| Patients can't copy/paste | Expected (role-based) | Log in as admin for clipboard |
| TOTP rejected | Clock skew | `timedatectl set-ntp true` |
| DB corruption | `PRAGMA integrity_check` | Restore from encrypted backup |

### Fortinet Certificate (End-User)
Direct users to install the Fortinet root CA:
- **Windows:** Right-click cert → Install Certificate → Trusted Root Certification Authorities
- **macOS:** `sudo security add-trusted-cert -d -r trustRoot -k /Library/Keychains/System.keychain ~/Desktop/fortinet-ca.pem`
- **Linux:** `sudo cp fortinet-ca.pem /usr/local/share/ca-certificates/ && sudo update-ca-certificates`
- **Browser bypass** (temporary): Type `thisisunsafe` on Chrome error page

---

## 12. Roadmap & Next Tasks

### Security & Reliability
- SMTP dry-run check from CLI (done: `scripts/check_smtp.py`)
- Admin lockout event notifications (optional email)
- Forced logout of all sessions after authenticator disable
- Reset-token entropy/length assertion and metrics logging

### Observability
- Security dashboard widget: failed logins in 24h, resets requested/completed
- Structured security logs for auth_* events with IP + user-agent hashes
- Retention cleanup telemetry (rows deleted per run)

### Usability
- Admin settings page for SMTP configuration test guidance
- Password policy helper text on reset page with live checks
- One-click copy-safe export of recent auth events

### Data Protection
- Optional hashing/redaction of audit details fields
- Configurable retention for notifications and messages
- Automatic purge for stale unverified candidates

### Testing
- SMTP test endpoint success/failure tests
- Retention cleanup guard tests
- Session invalidation after admin password change/reset tests

### Design System (Templates to Update)
**High priority:** patient_dashboard, calendar, patient_detail, edit_patient/add_patient
**Medium priority:** admin_profile, groups, manage_resources, messages
**Low priority:** login, register, index, resources

---

## 13. Changelog

Full development history: [`CHANGES.md`](../CHANGES.md) — 80+ sessions documented.

### Recent Sessions (Summary)

| Session | Date | Highlights |
|---------|------|------------|
| 79 | 2026-05-27 | Group Docs parsing improvements, cleaner imported patient notes |
| 78 | 2026-05-27 | CRM appointment fix, group Docs attendance parsing |
| 77 | 2026-05-08 | OAuth callback hardening, anonymous signed-state guard |
| 76 | 2026-05-07 | Server-rendered Google state, always-visible integration panel |
| — | 2026-04-18 | Security review: rate limiting, headers, webhook verification |

### Latest Git History (18d87e3)
```
18d87e3 Decouple calendar.py from app: move pure functions to utils.py
b78eb3e Patient portal: treatment plan admin form + patient view, goal tracking
a50add2 Clean dead code from models.py: strip 200 lines
55d01da High-impact fixes: FK indexes, LIMIT queries, logging
bac78be Search Phase 2: global admin search
a77028d Patient Portal Phase 2: cancel requests + approve/reject flow
88f5dc7 Billing Phase 1b: PDF receipt generation (fpdf2)
75d44e6 Billing Phase 1: service_types table, auto-numbered receipts
94e5f3b Patient portal: past appointments view, shared notes toggle
2965085 Appointment email reminders + SQL injection fix
a342103 i18n: complete Hebrew translations (685 keys, 100%)
```

---

*Generated from consolidation of README.md, AGENTS.md, DEPLOYMENT_GUIDE.md, DEPLOYMENT_QUICK_START.md, DEPLOYMENT_READY.md, DEPLOYMENT_STATUS.md, DEPLOYMENT_SUMMARY.md, DESIGN_UPDATE_GUIDE.md, FORTINET_CERTIFICATE_SETUP.md, LIVE_DEPLOYMENT.md, MIGRATION_INSTRUCTIONS.md, NEXT_TASKS.md, SECURITY_REVIEW.md, opencode-session-summary.md, pr_description.md, and verification/deployment_debug_2026-06-21.md.*
