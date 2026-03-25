#!/bin/bash
# ============================================================
#  job-agent — one-shot setup script
#  Run this once from the directory containing job_agent.zip
#  Usage: bash setup.sh
# ============================================================

set -e  # stop on any error

# ── Colors ───────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # no color

ok()   { echo -e "${GREEN}  ✅  $1${NC}"; }
info() { echo -e "${CYAN}  ──  $1${NC}"; }
warn() { echo -e "${YELLOW}  ⚠   $1${NC}"; }
fail() { echo -e "${RED}  ❌  $1${NC}"; exit 1; }
header() { echo -e "\n${BOLD}${CYAN}$1${NC}"; echo "  $(printf '─%.0s' {1..55})"; }

# ── Detect Python and pip ────────────────────────────────────
PYTHON=$(which python3 || which python)
PIP=$(which pip3 || which pip)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(dirname "$SCRIPT_DIR")"  # parent of job_agent/

echo ""
echo -e "${BOLD}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}║        job-agent setup                       ║${NC}"
echo -e "${BOLD}║        Riya Aggarwal's Job Pipeline          ║${NC}"
echo -e "${BOLD}╚══════════════════════════════════════════════╝${NC}"
echo ""
info "Python:      $PYTHON"
info "Pip:         $PIP"
info "Install dir: $INSTALL_DIR"
info "Package dir: $SCRIPT_DIR"

# ── Step 1: Install Python dependencies ─────────────────────
header "Step 1/4 — Installing Python dependencies"
$PIP install -r "$SCRIPT_DIR/requirements.txt" -q \
  && ok "Dependencies installed" \
  || fail "pip install failed — check requirements.txt"

# ── Step 2: Install the job-agent package ───────────────────
header "Step 2/4 — Installing job-agent package"
$PIP install -e "$SCRIPT_DIR" -q \
  && ok "Package installed (editable mode)" \
  || fail "pip install -e failed"

# ── Step 3: Fix the CLI entry point ─────────────────────────
header "Step 3/4 — Fixing CLI entry point"

JOB_AGENT_BIN=$(which job-agent 2>/dev/null || echo "")
if [ -z "$JOB_AGENT_BIN" ]; then
    # Find it in common locations
    for p in /opt/anaconda3/bin /opt/homebrew/bin /usr/local/bin ~/.local/bin; do
        if [ -f "$p/job-agent" ]; then
            JOB_AGENT_BIN="$p/job-agent"
            break
        fi
    done
fi

if [ -z "$JOB_AGENT_BIN" ]; then
    warn "Could not find job-agent binary — will create in /usr/local/bin"
    JOB_AGENT_BIN="/usr/local/bin/job-agent"
fi

info "Rewriting: $JOB_AGENT_BIN"

cat > "$JOB_AGENT_BIN" << SCRIPT
#!$PYTHON
import sys
sys.path.insert(0, "$INSTALL_DIR")
from job_agent.cli.main import main
main()
SCRIPT

chmod +x "$JOB_AGENT_BIN"
ok "CLI entry point fixed → $JOB_AGENT_BIN"

# ── Step 4: Verify ───────────────────────────────────────────
header "Step 4/4 — Verifying installation"

# Check package importable
$PYTHON -c "import job_agent; print('    Package version:', job_agent.__version__)" \
  && ok "Package imports correctly" \
  || fail "Package not importable — check sys.path"

# Run tests
info "Running test suite..."
cd "$INSTALL_DIR"
$PYTHON "$SCRIPT_DIR/run_tests.py" 2>&1 | grep -E "(PASSED|FAILED|✅|❌)"
ok "Tests complete"

# Check playwright
if $PYTHON -c "from playwright.sync_api import sync_playwright" 2>/dev/null; then
    ok "Playwright installed"
    # Check if browser is installed
    if $PYTHON -c "
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        b = p.chromium.launch(headless=True)
        b.close()
        print('ok')
    except:
        print('no_browser')
" 2>/dev/null | grep -q "ok"; then
        ok "Playwright browser ready"
    else
        warn "Playwright browser not installed — run: playwright install chromium"
        warn "(Only needed for 'job-agent apply'. All other commands work without it.)"
    fi
else
    warn "Playwright not installed — run: pip install playwright && playwright install chromium"
fi

# ── Done ─────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}╔══════════════════════════════════════════════╗${NC}"
echo -e "${BOLD}${GREEN}║  ✅  Setup complete!                          ║${NC}"
echo -e "${BOLD}${GREEN}╚══════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${BOLD}Quick start:${NC}"
echo ""
echo "  job-agent collect --dry-run --limit 10    # test run, store nothing"
echo "  job-agent collect --source greenhouse      # collect real jobs"
echo "  job-agent shortlist                        # see matches"
echo "  job-agent view <JOB_ID>                   # inspect a job"
echo "  job-agent tailor <JOB_ID>                 # generate resume"
echo "  job-agent cover-letter <JOB_ID>           # generate cover letter"
echo "  job-agent apply <JOB_ID>                  # assisted apply"
echo "  job-agent stats                            # pipeline stats"
echo ""
echo -e "${CYAN}  Data stored at: ~/.job_agent/${NC}"
echo -e "${CYAN}  Logs at:        ~/.job_agent/logs/${NC}"
echo ""
