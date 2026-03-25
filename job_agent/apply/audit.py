"""
Greenhouse Application Auditor

Opens real job pages, inspects every field, and reports:
  ✅ Would fill correctly
  ⚠  Would fill but may be wrong  
  ❌ Cannot fill — needs fixing

Run: python job_agent/apply/audit.py
"""

import re
import sys
from pathlib import Path

# Add to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from job_agent.apply.engine import (
    ID_FILLS, TEXT_PATTERNS, QUESTION_ANSWERS,
    SELECT_ANSWERS, REACT_SELECT_ANSWERS, TEXTAREA_PATTERNS,
    CHECKBOX_PATTERNS
)

# Test URLs — real Greenhouse applications
TEST_URLS = [
    ("Nuro (iframe type)",    "https://nuro.ai/careersitem?gh_jid=6338248"),
    ("Waymo (direct type)",   "https://careers.withwaymo.com/jobs?gh_jid=7438645"),
    ("Cloudflare",            "https://boards.greenhouse.io/cloudflare/jobs/7190684"),
]

def audit_page(name, url):
    from playwright.sync_api import sync_playwright

    print(f"\n{'='*65}")
    print(f"  AUDITING: {name}")
    print(f"  URL: {url}")
    print(f"{'='*65}")

    issues = []
    fills = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)  # headless for audit
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)

            # Dismiss banners
            for sel in ["button:has-text('Allow All')", "button:has-text('Accept')", "#onetrust-accept-btn-handler"]:
                try:
                    btn = page.query_selector(sel)
                    if btn and btn.is_visible():
                        btn.click()
                        page.wait_for_timeout(800)
                        break
                except Exception:
                    pass

            # Get form context
            form = page
            for frame in page.frames:
                if "greenhouse.io/embed/job_app" in frame.url:
                    form = frame
                    print(f"  Type: Greenhouse iframe (Type A)")
                    break
            else:
                print(f"  Type: Direct page (Type B)")

            contexts = [form, page] if form is not page else [page]

            # Audit all inputs
            print(f"\n  TEXT INPUTS:")
            seen = set()
            for ctx in contexts:
                for inp in ctx.query_selector_all(
                    "input[type=text], input[type=email], input[type=tel], "
                    "input[type=url], input:not([type])"
                ):
                    try:
                        if not inp.is_visible():
                            continue
                        box = inp.bounding_box()
                        pos = (round(box["x"]), round(box["y"])) if box else id(inp)
                        if pos in seen:
                            continue
                        seen.add(pos)

                        fid = inp.get_attribute("id") or ""
                        fname = inp.get_attribute("name") or ""
                        placeholder = (inp.get_attribute("placeholder") or "").lower()
                        label_text = ""
                        if fid:
                            lbl = ctx.query_selector(f"label[for='{fid}']")
                            if lbl:
                                label_text = lbl.inner_text().strip()
                        combined = f"{fid} {fname} {placeholder} {label_text}"

                        # Check if we'd fill it
                        if fid in ID_FILLS:
                            value = ID_FILLS[fid]
                            fills.append(f"    ✅ #{fid} -> '{value}'")
                        elif fid.startswith("question_"):
                            matched = None
                            for pattern, val in QUESTION_ANSWERS:
                                if re.search(pattern, label_text, re.IGNORECASE):
                                    matched = val
                                    break
                            if matched is not None:
                                fills.append(f"    ✅ {label_text[:45]} -> '{matched[:30]}'")
                            else:
                                issues.append(f"    ❌ UNKNOWN QUESTION: '{label_text[:60]}'")
                        else:
                            matched = None
                            for pattern, val in TEXT_PATTERNS:
                                if re.search(pattern, combined, re.IGNORECASE):
                                    matched = val
                                    break
                            if matched is not None:
                                fills.append(f"    ✅ '{label_text or fid or placeholder}'[:40] -> '{matched[:30]}'")
                            elif combined.strip():
                                issues.append(f"    ⚠  UNFILLED INPUT: id='{fid}' label='{label_text[:40]}' placeholder='{placeholder[:30]}'")
                    except Exception:
                        pass

            # Audit textareas
            print(f"\n  TEXTAREAS:")
            for ctx in contexts:
                for ta in ctx.query_selector_all("textarea"):
                    try:
                        if not ta.is_visible():
                            continue
                        fid = ta.get_attribute("id") or ""
                        placeholder = (ta.get_attribute("placeholder") or "").lower()
                        label_text = ""
                        if fid:
                            lbl = ctx.query_selector(f"label[for='{fid}']")
                            if lbl:
                                label_text = lbl.inner_text().strip()
                        combined = f"{label_text} {placeholder}"
                        matched = None
                        for pattern, val in TEXTAREA_PATTERNS:
                            if re.search(pattern, combined, re.IGNORECASE):
                                matched = val
                                break
                        if matched is not None:
                            if matched:
                                fills.append(f"    ✅ textarea '{label_text[:40]}' -> '{matched[:30]}'")
                            else:
                                fills.append(f"    ✅ textarea '{label_text[:40]}' -> (left blank)")
                        elif "recaptcha" not in fid.lower():
                            issues.append(f"    ⚠  UNFILLED TEXTAREA: '{label_text or placeholder}'[:50]")
                    except Exception:
                        pass

            # Audit native selects
            print(f"\n  NATIVE SELECTS:")
            for ctx in contexts:
                for sel_el in ctx.query_selector_all("select"):
                    try:
                        if not sel_el.is_visible():
                            continue
                        label_text = ctx.evaluate("""(sel) => {
                            let el = sel;
                            for (let i = 0; i < 8; i++) {
                                el = el.parentElement;
                                if (!el) break;
                                const lbl = el.querySelector('label');
                                if (lbl) return lbl.innerText.trim();
                            }
                            return '';
                        }""", sel_el)

                        opts = [o.inner_text().strip() for o in sel_el.query_selector_all("option") if o.inner_text().strip()]
                        matched_answer = None
                        matched_opt = None
                        for pattern, answer in SELECT_ANSWERS:
                            if re.search(pattern, label_text, re.IGNORECASE):
                                matched_answer = answer
                                for opt in opts:
                                    t_norm = opt.lower().replace("\u2019", "'").replace("-", " ")
                                    a_norm = answer.lower().replace("\u2019", "'").replace("-", " ")
                                    if a_norm[:20] in t_norm:
                                        matched_opt = opt
                                        break
                                break

                        if matched_answer and matched_opt:
                            fills.append(f"    ✅ SELECT '{label_text[:40]}' -> '{matched_opt[:40]}'")
                        elif matched_answer:
                            issues.append(f"    ❌ SELECT '{label_text[:40]}': answer='{matched_answer[:30]}' NOT FOUND in options: {opts[:4]}")
                        elif label_text and label_text not in ["Departments", "Locations"]:
                            issues.append(f"    ⚠  SELECT NO PATTERN: '{label_text[:40]}' options={opts[:3]}")
                    except Exception:
                        pass

            # Audit React Selects
            print(f"\n  REACT SELECTS (EEO):")
            for ctx in contexts:
                for label_el in ctx.query_selector_all("label"):
                    try:
                        label_text = label_el.inner_text().strip()
                        if not label_text:
                            continue
                        control = ctx.evaluate_handle("""(label) => {
                            let el = label;
                            for (let i = 0; i < 8; i++) {
                                if (!el) break;
                                const ctrl = el.querySelector('.select__control');
                                if (ctrl) return ctrl;
                                el = el.parentElement;
                            }
                            return null;
                        }""", label_el).as_element()

                        if not control or not control.is_visible():
                            continue

                        matched = None
                        for pattern, ans in REACT_SELECT_ANSWERS:
                            if re.search(pattern, label_text, re.IGNORECASE):
                                matched = ans
                                break

                        if matched:
                            fills.append(f"    ✅ REACT '{label_text[:40]}' -> '{matched[:30]}'")
                        else:
                            issues.append(f"    ⚠  REACT NO PATTERN: '{label_text[:40]}'")
                    except Exception:
                        pass

            # Audit checkboxes
            print(f"\n  CHECKBOXES:")
            for ctx in contexts:
                for cb in ctx.query_selector_all("input[type=checkbox]"):
                    try:
                        if not cb.is_visible():
                            continue
                        cb_id = cb.get_attribute("id") or ""
                        label_text = ""
                        if cb_id:
                            lbl = ctx.query_selector(f"label[for='{cb_id}']")
                            if lbl:
                                label_text = lbl.inner_text().lower()
                        parent_text = ctx.evaluate(
                            "el => el.parentElement ? el.parentElement.innerText.toLowerCase().substring(0, 80) : ''", cb
                        )
                        combined = f"{cb_id} {label_text} {parent_text}"
                        if re.search(CHECKBOX_PATTERNS[0], combined, re.IGNORECASE):
                            fills.append(f"    ✅ CHECKBOX: '{(label_text or parent_text)[:50]}'")
                        else:
                            issues.append(f"    ⚠  CHECKBOX NOT MATCHED: '{(label_text or parent_text)[:50]}'")
                    except Exception:
                        pass

            # Print results
            print("\n  WILL FILL:")
            for f in fills:
                print(f)

            if issues:
                print(f"\n  ISSUES ({len(issues)}):")
                for i in issues:
                    print(i)
            else:
                print(f"\n  NO ISSUES ✅")

            return len(issues)

        except Exception as e:
            print(f"  ERROR: {e}")
            return 99
        finally:
            browser.close()


if __name__ == "__main__":
    total_issues = 0
    for name, url in TEST_URLS:
        total_issues += audit_page(name, url)

    print(f"\n{'='*65}")
    print(f"  TOTAL ISSUES: {total_issues}")
    print(f"{'='*65}")
