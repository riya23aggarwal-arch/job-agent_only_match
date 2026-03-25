"""
Deep Greenhouse Audit Script

Opens real job pages, fills them using the engine, captures:
- Every field found (id, label, type, options)
- What was filled vs what was left empty
- Any errors
- Screenshot of final state

Share the output with Claude to fix all remaining issues.

Usage:
  cd ~/jobpilotv4
  python job_agent/apply/deep_audit.py 2>&1 | tee ~/Desktop/audit_report.txt
  # Then share audit_report.txt
"""

import json
import re
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# ── Job URLs to audit ─────────────────────────────────────────────────────────
# These cover both Greenhouse form types and multiple companies
TEST_JOBS = [
    # Type A — iframe embed (most Greenhouse companies)
    ("Nuro",        "https://nuro.ai/careersitem?gh_jid=6338248"),
    ("Cloudflare",  "https://boards.greenhouse.io/cloudflare/jobs/6523689002"),
    ("Fastly",      "https://boards.greenhouse.io/fastly/jobs/6457196001"),
    ("Waymo",       "https://careers.withwaymo.com/jobs?gh_jid=7438645"),  # Type B
]

from job_agent.apply.engine import ApplyEngine, RESUME_DIR
from job_agent.profile import CANDIDATE_PROFILE
P = CANDIDATE_PROFILE


def run_audit():
    from playwright.sync_api import sync_playwright

    engine = ApplyEngine()
    pdf = engine._find_pdf(None)

    print("=" * 70)
    print("GREENHOUSE DEEP AUDIT")
    print(f"Resume: {pdf.name if pdf else 'NOT FOUND'}")
    print(f"Jobs to audit: {len(TEST_JOBS)}")
    print("=" * 70)

    if not pdf:
        print(f"\nERROR: No resume PDF found at {RESUME_DIR}")
        print("Fix: cp ~/path/to/resume.pdf ~/.job_agent/resumes/Riya_Aggarwal_Resume.pdf")
        sys.exit(1)

    all_results = []

    with sync_playwright() as pw:
        for company, url in TEST_JOBS:
            print(f"\n\n{'#'*70}")
            print(f"# AUDITING: {company}")
            print(f"# URL: {url}")
            print(f"{'#'*70}")
            result = audit_one(pw, engine, pdf, company, url)
            all_results.append(result)
            time.sleep(3)

    # Print final report
    print("\n\n" + "=" * 70)
    print("FINAL REPORT — COPY THIS TO CLAUDE")
    print("=" * 70)
    for r in all_results:
        pct = int(r["filled"] / max(r["total"], 1) * 100)
        print(f"\n{r['company']} ({pct}% filled, {r['issues']} issues):")
        for issue in r["issues_list"]:
            print(f"  {issue}")
        if not r["issues_list"]:
            print("  All fields filled correctly")

    total = sum(r["issues"] for r in all_results)
    print(f"\nTOTAL ISSUES: {total}")


def audit_one(pw, engine, pdf, company, url):
    result = {
        "company": company, "url": url,
        "filled": 0, "total": 0, "issues": 0, "issues_list": []
    }

    browser = pw.chromium.launch(headless=False, slow_mo=60)
    page = browser.new_page(viewport={"width": 1280, "height": 900})

    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)
        print(f"Loaded: {page.title()}")

        # Dismiss banner
        for sel in [
            "button:has-text('Allow All')",
            "button:has-text('Accept All')",
            "button:has-text('Accept')",
            "#onetrust-accept-btn-handler",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1000)
                    print(f"Banner dismissed")
                    break
            except Exception:
                pass

        # Detect form type
        form = page
        for frame in page.frames:
            if "greenhouse.io/embed/job_app" in frame.url:
                form = frame
                print(f"Form type: A (iframe at {frame.url[:60]})")
                break
        else:
            print(f"Form type: B (direct page)")

        is_iframe = form is not page

        # ── SCAN ALL FIELDS BEFORE FILLING ──
        print("\n--- SCANNING FIELDS ---")
        fields_before = scan_all_fields(page, form, is_iframe)
        print(f"Found {len(fields_before)} fields")
        for f in fields_before:
            print(f"  FIELD: type={f['type']:<12} required={'Y' if f['req'] else 'N'} "
                  f"label='{f['label'][:45]}' "
                  f"{'options=' + str(f.get('opts', [])[:3]) if f['type'] == 'select' else ''}")

        # ── FILL USING ENGINE ──
        print("\n--- FILLING ---")
        engine._resume_uploaded = False
        try:
            engine._fill_by_id(form)
        except Exception as e:
            print(f"ERROR _fill_by_id: {e}")
        try:
            engine._fill_phone(page, form)
        except Exception as e:
            print(f"ERROR _fill_phone: {e}")
        try:
            engine._fill_text_inputs(page, form)
        except Exception as e:
            print(f"ERROR _fill_text_inputs: {e}")
        try:
            engine._fill_textareas(page, form)
        except Exception as e:
            print(f"ERROR _fill_textareas: {e}")
        try:
            engine._fill_native_selects(page)
            if is_iframe:
                engine._fill_native_selects(form)
        except Exception as e:
            print(f"ERROR _fill_native_selects: {e}")
        try:
            engine._fill_react_selects(form if is_iframe else page)
        except Exception as e:
            print(f"ERROR _fill_react_selects: {e}")
        try:
            page.wait_for_timeout(1000)
            engine._fill_race(form if is_iframe else page)
        except Exception as e:
            print(f"ERROR _fill_race: {e}")
        try:
            engine._fill_checkboxes(page)
            if is_iframe:
                engine._fill_checkboxes(form)
        except Exception as e:
            print(f"ERROR _fill_checkboxes: {e}")
        try:
            engine._upload_resume(form, pdf)
        except Exception as e:
            print(f"ERROR _upload_resume: {e}")

        # ── SCAN FIELDS AFTER FILLING ──
        print("\n--- RESULTS AFTER FILLING ---")
        fields_after = scan_all_fields(page, form, is_iframe)

        filled = 0
        issues = 0

        for f in fields_after:
            result["total"] += 1
            label = f["label"]
            val = f["val"]
            req = f["req"]
            ftype = f["type"]

            if ftype in ("text", "email", "tel", "url", "textarea"):
                if val.strip():
                    print(f"  OK  {ftype:<10} '{label[:45]}' = '{val[:40]}'")
                    filled += 1
                elif req:
                    print(f"  ERR {ftype:<10} REQUIRED EMPTY: '{label[:50]}'")
                    result["issues_list"].append(f"REQUIRED EMPTY [{ftype}]: {label}")
                    issues += 1
                else:
                    print(f"  --  {ftype:<10} optional empty: '{label[:45]}'")

            elif ftype == "select":
                opts = f.get("opts", [])
                if val.strip():
                    print(f"  OK  select     '{label[:45]}' = '{val[:40]}'")
                    filled += 1
                elif req:
                    print(f"  ERR select     REQUIRED EMPTY: '{label[:50]}'")
                    print(f"      Options: {opts}")
                    result["issues_list"].append(
                        f"SELECT EMPTY: {label} | opts: {opts[:5]}"
                    )
                    issues += 1
                else:
                    print(f"  --  select     optional empty: '{label[:45]}'")
                    print(f"      Options: {opts}")

            elif ftype == "react_select":
                if val.strip() and "select..." not in val.lower():
                    print(f"  OK  react      '{label[:45]}' = '{val[:40]}'")
                    filled += 1
                else:
                    # React selects are voluntary EEO — note but not error
                    print(f"  !!  react      UNFILLED: '{label[:50]}'")
                    result["issues_list"].append(f"REACT UNFILLED: {label}")
                    issues += 1

            elif ftype == "checkbox":
                if val == "checked":
                    print(f"  OK  checkbox   '{label[:55]}'")
                    filled += 1
                elif req:
                    print(f"  ERR checkbox   REQUIRED UNCHECKED: '{label[:50]}'")
                    result["issues_list"].append(f"CHECKBOX UNCHECKED: {label}")
                    issues += 1
                else:
                    print(f"  --  checkbox   unchecked (optional): '{label[:45]}'")

            elif ftype == "file":
                if val:
                    print(f"  OK  file       '{label[:45]}' uploaded")
                    filled += 1
                else:
                    print(f"  ERR file       RESUME NOT UPLOADED")
                    result["issues_list"].append("RESUME NOT UPLOADED")
                    issues += 1

        result["filled"] = filled
        result["issues"] = issues

        print(f"\nSUMMARY: {filled}/{result['total']} filled, {issues} issues")

        # Screenshot
        shot = Path(f"/tmp/audit_{company.lower().replace(' ', '_')}.png")
        try:
            page.screenshot(path=str(shot), full_page=True)
            print(f"Screenshot: {shot}")
        except Exception:
            pass

        # Keep open so you can inspect
        print("\nBrowser stays open 8 seconds — inspect the form...")
        time.sleep(8)

    except Exception as e:
        print(f"FATAL ERROR: {e}")
        traceback.print_exc()
        result["issues"] = 99
        result["issues_list"].append(f"FATAL: {e}")
    finally:
        browser.close()

    return result


def scan_all_fields(page, form, is_iframe):
    """Scan every visible fillable field and return its current state."""
    fields = []
    seen = set()
    ctxs = [form, page] if is_iframe else [page]

    for ctx in ctxs:
        # Text / email / tel / url inputs
        for inp in ctx.query_selector_all(
            "input[type=text], input[type=email], input[type=tel],"
            "input[type=url], input:not([type])"
        ):
            try:
                if not inp.is_visible() or inp.is_disabled():
                    continue
                fid = inp.get_attribute("id") or ""
                # Skip hidden/utility inputs
                if any(x in fid.lower() for x in
                       ["recaptcha", "iti-", "search", "g-recaptcha"]):
                    continue

                box = inp.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(inp)
                if pos in seen:
                    continue
                seen.add(pos)

                label = build_label(ctx, inp)
                req = (inp.get_attribute("required") is not None or
                       inp.get_attribute("aria-required") == "true" or
                       "*" in label)
                val = inp.input_value()
                itype = inp.get_attribute("type") or "text"

                fields.append({"type": itype, "id": fid,
                               "label": label, "val": val, "req": req})
            except Exception:
                pass

        # Textareas
        for ta in ctx.query_selector_all("textarea"):
            try:
                if not ta.is_visible():
                    continue
                fid = ta.get_attribute("id") or ""
                if "recaptcha" in fid.lower():
                    continue
                box = ta.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(ta)
                if pos in seen:
                    continue
                seen.add(pos)
                label = build_label(ctx, ta)
                req = ta.get_attribute("required") is not None
                val = ta.input_value()
                fields.append({"type": "textarea", "id": fid,
                               "label": label, "val": val, "req": req})
            except Exception:
                pass

        # Native selects
        for sel_el in ctx.query_selector_all("select"):
            try:
                if not sel_el.is_visible():
                    continue
                box = sel_el.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(sel_el)
                if pos in seen:
                    continue
                seen.add(pos)

                label = ctx.evaluate("""(sel) => {
                    let el = sel;
                    for (let i = 0; i < 10; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const lbl = el.querySelector('label');
                        if (lbl) return lbl.innerText.trim();
                    }
                    return sel.name || sel.id || '';
                }""", sel_el)

                if label in ["Departments", "Locations"]:
                    continue

                opts = [o.inner_text().strip() for o in
                        sel_el.query_selector_all("option") if o.inner_text().strip()]
                val = sel_el.input_value()
                req = sel_el.get_attribute("required") is not None or "(required)" in label
                fields.append({"type": "select", "label": label,
                               "val": val, "req": req, "opts": opts})
            except Exception:
                pass

        # React selects
        for label_el in ctx.query_selector_all("label"):
            try:
                label_text = label_el.inner_text().strip()
                if not label_text:
                    continue
                control = ctx.evaluate_handle("""(lbl) => {
                    let el = lbl;
                    for (let i = 0; i < 8; i++) {
                        if (!el) break;
                        const c = el.querySelector('.select__control');
                        if (c) return c;
                        el = el.parentElement;
                    }
                    return null;
                }""", label_el).as_element()
                if not control or not control.is_visible():
                    continue
                box = control.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(control)
                if pos in seen:
                    continue
                seen.add(pos)
                val_el = control.query_selector(
                    ".select__single-value, .select__placeholder"
                )
                val = val_el.inner_text().strip() if val_el else ""
                fields.append({"type": "react_select", "label": label_text,
                               "val": val, "req": False})
            except Exception:
                pass

        # Checkboxes
        for cb in ctx.query_selector_all("input[type=checkbox]"):
            try:
                if not cb.is_visible():
                    continue
                box = cb.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(cb)
                if pos in seen:
                    continue
                seen.add(pos)
                cb_id = cb.get_attribute("id") or ""
                label_text = ""
                if cb_id:
                    lbl = ctx.query_selector(f"label[for='{cb_id}']")
                    if lbl:
                        label_text = lbl.inner_text().strip()
                if not label_text:
                    label_text = ctx.evaluate(
                        "el => el.parentElement ? el.parentElement.innerText.substring(0,80) : ''",
                        cb
                    ).strip()
                val = "checked" if cb.is_checked() else ""
                req = re.search(
                    r"certif|privacy|submitting|true.*correct", label_text, re.IGNORECASE
                ) is not None
                fields.append({"type": "checkbox", "id": cb_id,
                               "label": label_text[:80], "val": val, "req": req})
            except Exception:
                pass

        # File inputs
        for fi in ctx.query_selector_all("input[type=file]"):
            try:
                if not fi.is_visible():
                    continue
                box = fi.bounding_box()
                pos = (round(box["x"]), round(box["y"])) if box else id(fi)
                if pos in seen:
                    continue
                seen.add(pos)
                fid = (fi.get_attribute("id") or "").lower()
                label = build_label(ctx, fi)
                parent = ctx.evaluate(
                    "el => el.parentElement ? el.parentElement.innerText : ''", fi
                )
                has_file = any(x in parent for x in [".pdf", ".doc", "Aggarwal"])
                req = "cover" not in fid
                fields.append({"type": "file", "id": fid,
                               "label": label or fid, "val": "uploaded" if has_file else "",
                               "req": req})
            except Exception:
                pass

    return fields


def build_label(ctx, el) -> str:
    parts = []
    for attr in ["id", "name", "placeholder", "aria-label"]:
        v = el.get_attribute(attr) or ""
        if v and "recaptcha" not in v.lower():
            parts.append(v)
    try:
        fid = el.get_attribute("id")
        if fid:
            lbl = ctx.query_selector(f"label[for='{fid}']")
            if lbl:
                parts.append(lbl.inner_text().strip())
    except Exception:
        pass
    return " | ".join(parts)


if __name__ == "__main__":
    run_audit()
