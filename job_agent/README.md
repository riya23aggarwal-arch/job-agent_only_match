# job-agent

**Riya's personal job application system.**

A production-quality, fully modular pipeline that collects jobs, scores them against your profile, stores only high-value matches, and assists with applications end-to-end.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    STREAMING PIPELINE                       │
│                                                             │
│  Collectors → Parser → Scorer → Decision Gate → Storage    │
│                                      │                      │
│                               score >= 90  → APPLY_NOW ──► DB
│                               score 75-89  → REVIEW    ──► DB
│                               score < 75   → DISCARD   ──► Log
└─────────────────────────────────────────────────────────────┘
```

**Key principle:** Jobs are NOT stored en masse. Each job flows through the pipeline and is only persisted if it's a strong match.

---

## Folder Structure

```
job_agent/
├── models.py               # Core data classes (RawJob, ScoredJob, StoredJob, etc.)
├── profile.py              # Riya's candidate profile — single source of truth
├── pipeline.py             # Streaming pipeline orchestrator
│
├── collectors/
│   ├── base.py             # BaseCollector (HTTP, rate limiting, parsing utilities)
│   ├── greenhouse.py       # Greenhouse JSON API collector
│   ├── lever.py            # Lever JSON API collector
│   ├── workday.py          # Workday career page collector
│   └── career_pages.py     # Generic career page + Amazon Jobs collector
│
├── scoring/
│   └── engine.py           # Weighted keyword scoring engine (no API calls)
│
├── storage/
│   └── database.py         # SQLite database layer
│
├── resume/
│   └── tailor.py           # Tailored resume generator (md / txt / LaTeX)
│
├── cover_letter/
│   └── generator.py        # Cover letter, recruiter email, Q&A generator
│
├── apply/
│   └── engine.py           # Playwright-based assisted apply engine
│
├── tracker/
│   └── tracker.py          # Application board and pipeline state
│
├── cli/
│   └── main.py             # Typer CLI — all commands
│
└── tests/
    ├── test_scoring.py      # 10 scoring engine tests
    ├── test_database.py     # 9 database layer tests
    └── test_pipeline.py     # 4 integration tests
```

---

## Database Schema

```sql
-- High-value jobs only (APPLY_NOW + REVIEW)
CREATE TABLE jobs (
    job_id           TEXT PRIMARY KEY,
    company          TEXT,
    role             TEXT,
    location         TEXT,
    description      TEXT,
    requirements     TEXT,
    apply_url        TEXT,
    source           TEXT,
    date_found       TEXT,
    score            INTEGER,
    decision         TEXT,        -- 'apply_now' | 'review'
    matched_skills   TEXT,        -- JSON array
    missing_skills   TEXT,        -- JSON array
    explanation      TEXT,
    status           TEXT,        -- shortlisted | ready_to_apply | applied | interview | rejected | offer
    notes            TEXT,
    date_applied     TEXT,
    tailored_resume_path  TEXT,
    cover_letter_path     TEXT,
    remote           INTEGER,
    salary_range     TEXT,
    created_at       TEXT
);

-- Every discarded job with reason
CREATE TABLE discard_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    company     TEXT,
    role        TEXT,
    score       INTEGER,
    reason      TEXT,
    source      TEXT,
    apply_url   TEXT,
    date_found  TEXT,
    created_at  TEXT
);

-- One row per collection run for audit
CREATE TABLE pipeline_runs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at      TEXT,
    source      TEXT,
    collected   INTEGER,
    scored      INTEGER,
    apply_now   INTEGER,
    review      INTEGER,
    discarded   INTEGER,
    errors      INTEGER
);
```

Database is stored at `~/.job_agent/jobs.db`.

---

## Scoring Engine

**Decision thresholds:**
| Score | Decision |
|-------|----------|
| ≥ 90  | `APPLY_NOW` — stored, high priority |
| 75–89 | `REVIEW`    — stored, review manually |
| < 75  | `DISCARD`   — logged only, not stored |

**Weights:**

| Category | Skills | Weight |
|----------|--------|--------|
| **High** | C, Linux internals, device drivers, BSP, hardware bring-up, kernel debugging, networking, optics, firmware | +10 each |
| **Medium** | Python, automation, debugging, shell scripting, PyATS, pytest, GDB | +5 each |
| **Low** | SQL, git, CI/CD, embedded systems | +2 each |
| **Penalty** | React, Angular, iOS, Android, ML engineer, data science | -15 each |
| **Bonuses** | Role title match, Bay Area/Remote location, seniority fit | +4–8 |

---

## Installation

```bash
# 1. Clone / copy this folder
cd job_agent

# 2. Install dependencies
pip install -r requirements.txt

# 3. Install Playwright browser
playwright install chromium

# 4. Install CLI
pip install -e .
```

---

## Commands

### Collect jobs from all sources
```bash
job-agent collect
job-agent collect --source greenhouse
job-agent collect --source lever
job-agent collect --source workday
job-agent collect --dry-run          # Score but don't store
```

### Score a single job
```bash
job-agent score --url "https://boards.greenhouse.io/..."
job-agent score --text "We need a Linux kernel engineer..." --role "Kernel Eng" --company Nvidia
```

### View shortlist
```bash
job-agent shortlist
job-agent shortlist --decision apply_now
job-agent shortlist --decision review
job-agent shortlist --min-score 85
```

### View a specific job
```bash
job-agent view A3F2C1B8
```

### Generate tailored resume
```bash
job-agent tailor A3F2C1B8
job-agent tailor A3F2C1B8 --format latex
job-agent tailor A3F2C1B8 --format text
```
Output saved to `~/.job_agent/resumes/`

### Generate cover letter + Q&A
```bash
job-agent cover-letter A3F2C1B8
```
Output saved to `~/.job_agent/cover_letters/` — three files:
- `recruiter_email_*.md` — short cold outreach / follow-up email
- `cover_letter_*.md` — full cover letter
- `qa_answers_*.md` — screening question answers

### Assisted apply (Playwright)
```bash
job-agent apply A3F2C1B8
job-agent apply A3F2C1B8 --mode semi_auto
```
Opens a real browser, autofills fields, **pauses before submit** — you always confirm.

### Track application status
```bash
job-agent track A3F2C1B8 --status applied
job-agent track A3F2C1B8 --status interview --notes "Phone screen with eng manager Friday"
job-agent track A3F2C1B8 --status rejected
```

### Pipeline stats
```bash
job-agent stats
```

### Export to CSV
```bash
job-agent export
job-agent export --output ~/Desktop/jobs.csv
job-agent export --decision apply_now
```

---

## Typical Workflow

```
# Monday morning — find new jobs
job-agent collect --source greenhouse
job-agent collect --source lever

# See what's new
job-agent shortlist --decision apply_now

# Pick a job (e.g., ID: A3F2C1B8)
job-agent view A3F2C1B8

# Prepare materials
job-agent tailor A3F2C1B8
job-agent cover-letter A3F2C1B8

# Apply
job-agent apply A3F2C1B8

# Update tracker
job-agent track A3F2C1B8 --status applied

# Stats
job-agent stats
```

---

## Adding More Companies

**Greenhouse** — add company slug to `collectors/greenhouse.py`:
```python
DEFAULT_COMPANIES = ["apple", "nvidia", "your-company-slug", ...]
```
Find the slug from: `https://boards.greenhouse.io/{slug}`

**Lever** — add company slug to `collectors/lever.py`:
```python
DEFAULT_COMPANIES = ["netlify", "your-company", ...]
```

**Workday** — add `(tenant, wd_number, site)` tuple to `collectors/workday.py`:
```python
DEFAULT_WORKDAY_COMPANIES = [
    ("cisco", 5, "Cisco"),
    ("yourcompany", 1, "External"),
]
```

---

## Running Tests

```bash
cd /path/to/  # parent of job_agent/
PYTHONPATH=. python job_agent/tests/test_scoring.py
PYTHONPATH=. python job_agent/tests/test_database.py
PYTHONPATH=. python job_agent/tests/test_pipeline.py
```

All 23 tests pass.

---

## Safety Guarantees

- **Never auto-submits** — the apply engine always pauses and requires explicit confirmation
- **Never bypasses login/captcha** — fully hands-off on auth
- **Never fabricates** — resume tailoring only reorders real bullets, never invents experience
- **Never stores garbage** — strict score threshold gates what enters the DB
- **Fully local** — no external API calls for scoring; all data stored on your machine

---

## Output Directories

| Path | Contents |
|------|----------|
| `~/.job_agent/jobs.db` | Main SQLite database |
| `~/.job_agent/resumes/` | Tailored resumes per job |
| `~/.job_agent/cover_letters/` | Cover letters, recruiter emails, Q&A |

---

## Extending the System

**Add a new collector:** Subclass `BaseCollector`, implement `_fetch_jobs()`, register in CLI.

**Tune scoring:** Edit weights in `scoring/engine.py` (`W_HIGH`, `W_MEDIUM`, `W_ANTI`).

**Add apply automations:** Extend `apply/engine.py` with company-specific field selectors.

**Custom resume sections:** Edit `resume/tailor.py` — add new focus types and bullet sets.
