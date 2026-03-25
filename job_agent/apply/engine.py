"""
Apply Engine — Greenhouse ATS

Two form types:
  Type A (iframe): Nuro, Cloudflare, Fastly, Ciena, Rambus
    Standard IDs: first_name, last_name, email, phone, country, resume
    Custom questions: question_XXXXXXXX text inputs (label[for=id])
    Auth questions (q_51376461/62): These are React Select dropdowns
      backed by hidden text inputs — fill by clicking React Select
    EEO: React Select (gender, hispanic, veteran, disability, race)
    Country: React Select (not a text input despite type=text)

  Type B (direct): Waymo (careers.withwaymo.com)
    Field IDs: form_first_name_X, form_last_name_X, form_email_X
    Phone: form_phone_number_X — has ITI country picker, use type()
    All dropdowns: native <select> (found by DOM walk, no for= attr)
    Textarea: legal name, LDAP text input
    Checkboxes: join talent, certify checkbox

AUDIT FINDINGS AND FIXES:
  1. Nuro country empty — country field IS a React Select, not text
  2. Nuro question_51376461/62 empty — these are React Selects,
     the text input behind them is read-only (React controlled)
     Fix: use React Select click approach, match by label
  3. Nuro resume not uploaded — file input not visible in headless,
     use force=True or check accept attribute
  4. Waymo phone empty — field id is form_phone_number_X_X_X,
     not matching "phone" pattern. Fix: match any id containing phone
  5. Waymo resume "not uploaded" — parent text check wrong.
     Fix: check if file input has files via JS
  6. React Select 'First Name*' = '+1' — phone number's React Select
     is being matched to First Name pattern. Fix: skip phone fields
"""

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from job_agent.models import StoredJob
from job_agent.profile import CANDIDATE_PROFILE

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

P          = CANDIDATE_PROFILE
RESUME_DIR = Path.home() / ".job_agent" / "resumes"
QA_CACHE   = Path.home() / ".job_agent" / "qa_cache.json"

# ── Standard Greenhouse Type A field IDs ──────────────────────────────────────
ID_FILLS: Dict[str, str] = {
    "first_name": "Riya",
    "last_name":  "Aggarwal",
    "email":      P["email"],
    "phone":      P["phone"],
    # country and EEO fields are React Selects — handled separately
}

# ── Text input patterns ───────────────────────────────────────────────────────
TEXT_PATTERNS: List[Tuple[str, str]] = [
    (r"first[_\-\s]?name|fname",             "Riya"),
    (r"last[_\-\s]?name|lname",              "Aggarwal"),
    (r"full[_\-\s]?name|legal[_\-\s]?name",  P["name"]),
    (r"\bemail\b",                            P["email"]),
    (r"linkedin",                             f"https://{P['linkedin']}"),
    (r"website|portfolio|blog",               f"https://{P['linkedin']}"),
    (r"ldap",                                 "raggarwal"),
    (r"\bcity\b",                             "San Jose"),
    (r"\bstate\b|\bprovince\b",               "CA"),
    (r"\bname\b",                             P["name"]),  # catch-all — LAST
]

# ── Textarea patterns ─────────────────────────────────────────────────────────
TEXTAREA_PATTERNS: List[Tuple[str, str]] = [
    (r"legal.*name|government.*id|provide.*full.*name|name.*government", P["name"]),
    (r"cover.*letter|additional.*info|anything.*else|tell.*us.*more",    ""),
]

# ── question_XXXXXXXX label patterns ─────────────────────────────────────────
QUESTION_ANSWERS: List[Tuple[str, str]] = [
    (r"authorized.*(work|employ)|work.*author",              "Yes"),
    (r"require.*sponsor|sponsor.*employ|future.*require",    "Yes"),
    (r"linkedin",                                            f"https://{P['linkedin']}"),
    (r"website|portfolio|github|personal\s+site",            f"https://{P['linkedin']}"),
    (r"hybrid|onsite|on.?site|days.*office",                 "Yes, open to onsite, hybrid, or remote"),
    (r"how.*hear|hear.*about|referral|source",               "LinkedIn"),
    (r"start.?date|available.*start|when.*start",            "ASAP"),
    (r"notice.?period",                                      "ASAP"),
    (r"salary|compensation|expected.*pay|desired.*pay",      "100000"),
    (r"currently.*employ|current.*job",                      "No"),
    (r"previously.*work|worked.*before|former.*employ",      "No"),
    (r"willing.*reloc|open.*reloc|relocat",                  "Yes"),
    (r"legal.*name|government.*id|provide.*full.*name",      P["name"]),
    (r"alphabet.*employ|google.*employ|former.*alphabet",    "No"),
    (r"acknowledge.*privacy|privacy.*policy|candidate.*privacy", "Yes"),
    (r"ldap",                                                "raggarwal"),
    (r"certif|true.*correct|information.*provided",          "Yes"),
]

# ── Native <select> answers (Waymo — found by DOM walk) ──────────────────────
SELECT_ANSWERS: List[Tuple[str, str]] = [
    (r"work.*author",                                         "I require, or in the future will require, Waymo"),
    (r"candidate.*privacy|acknowledge.*policy|review.*acknowledge", "I acknowledge that I have read"),
    (r"alphabet.*employ|google.*employ|former.*alphabet",     "Never worked at Alphabet"),
    (r"how.*hear.*opportun|hear.*about.*opportun",            "LinkedIn"),
    (r"how.*hear|hear.*about|referral|source",                "LinkedIn"),
    (r"\bgender\b",                                           "Female"),
    (r"hispanic|latino",                                      "No"),
    (r"race|ethnicity",                                       "Decline"),
    (r"veteran",                                              "not a protected veteran"),
    (r"disability",                                           "No, I do not"),
    (r"\bcountry\b",                                          "United States"),
    (r"sponsor|visa|immigr|require.*work",                    "I require"),
]

# ── React Select answers (Greenhouse iframe) ──────────────────────────────────
# These labels match what's visible in the form
REACT_SELECT_ANSWERS: List[Tuple[str, str]] = [
    # Auth questions in Nuro (question_51376461, question_51376462)
    (r"authorized.*(work|employ)|work.*author",   "Yes"),
    (r"require.*sponsor|sponsor.*employ|future.*require", "Yes"),
    # Country field
    (r"\bcountry\b",                              "United States"),
    # EEO fields
    (r"\bgender\b",                               "Female"),
    (r"hispanic|latino",                          "No"),
    (r"veteran",                                  "not a protected veteran"),
    (r"disability",                               "No, I do not"),
    # Race handled separately (no for= attribute)
]

# ── Checkbox patterns ─────────────────────────────────────────────────────────
CHECKBOX_PATTERN = r"privacy|acknowledge|consent|agree|policy|terms|certif|true.*correct|information.*provided"


@dataclass
class ApplyContext:
    job: StoredJob
    resume_path: Optional[Path]
    cover_letter_path: Optional[Path]
    mode: str = "assisted"
    qa_answers: Optional[Dict] = None


class ApplyEngine:

    def run(self, ctx: ApplyContext) -> bool:
        if not PLAYWRIGHT_AVAILABLE:
            print("Playwright not installed: pip install playwright && playwright install chromium")
            return False
        if not ctx.job.apply_url:
            print("No apply URL")
            return False
        if any(s in ctx.job.apply_url for s in ["community.workday", "invalid-url"]):
            print(f"Invalid URL — search manually: {ctx.job.company} {ctx.job.role} careers")
            return False

        pdf = self._find_pdf(ctx.resume_path)
        if not pdf:
            print(f"No PDF resume. Copy to: {RESUME_DIR}/Riya_Aggarwal_Resume.pdf")
            return False

        print(f"\n{'='*65}")
        print(f"  Applying: {ctx.job.role} @ {ctx.job.company}")
        print(f"  URL:      {ctx.job.apply_url}")
        print(f"  Resume:   {pdf.name}")
        print(f"{'='*65}\n")

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False, slow_mo=60)
            bctx = browser.new_context(viewport={"width": 1280, "height": 900})
            page = bctx.new_page()

            try:
                page.goto(ctx.job.apply_url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                print(f"Loaded: {page.title()}\n")

                self._dismiss_banners(page)

                form = self._get_form_context(page)
                is_iframe = form is not page
                if is_iframe:
                    print("Type A: Greenhouse iframe\n")
                else:
                    print("Type B: Direct page\n")

                # Fill in order
                self._fill_by_id(form)
                self._fill_phone(page, form)
                self._fill_text_inputs(page, form)
                self._fill_textareas(page, form)

                # Native selects (Waymo) — BOTH page and form
                self._fill_native_selects(page)
                if is_iframe:
                    self._fill_native_selects(form)

                # React selects (Greenhouse EEO + auth + country)
                self._fill_react_selects(form if is_iframe else page)

                # Race appears after Hispanic selection
                page.wait_for_timeout(1000)
                self._fill_race(form if is_iframe else page)

                # Checkboxes
                self._fill_checkboxes(page)
                if is_iframe:
                    self._fill_checkboxes(form)

                # Upload resume
                self._resume_uploaded = False
                self._upload_resume(form, pdf)
                if not self._resume_uploaded:
                    self._upload_resume(page, pdf)

                self._print_review(page, form)
                return self._gate(page)

            except Exception as e:
                logger.error(f"Apply error: {e}", exc_info=True)
                print(f"\nError: {e}")
                input("Press Enter to close...")
                return False
            finally:
                browser.close()

    # ── Banners ───────────────────────────────────────────────────────────────

    def _dismiss_banners(self, page):
        for sel in [
            "button:has-text('Allow All')",
            "button:has-text('Accept All')",
            "button:has-text('Accept all cookies')",
            "button:has-text('Accept Cookies')",
            "button:has-text('Accept')",
            "button:has-text('I Accept')",
            "#onetrust-accept-btn-handler",
        ]:
            try:
                btn = page.query_selector(sel)
                if btn and btn.is_visible():
                    btn.click()
                    page.wait_for_timeout(1000)
                    print("Banner dismissed\n")
                    return
            except Exception:
                pass

    # ── Form context ──────────────────────────────────────────────────────────

    def _get_form_context(self, page):
        page.wait_for_timeout(1000)
        for frame in page.frames:
            if "greenhouse.io/embed/job_app" in frame.url:
                return frame
            if "lever.co/apply" in frame.url:
                return frame
        return page

    # ── Fill by ID ────────────────────────────────────────────────────────────

    def _fill_by_id(self, ctx):
        filled = 0
        for fid, value in ID_FILLS.items():
            try:
                el = ctx.query_selector(f"#{fid}")
                if not el or not el.is_visible():
                    continue
                if el.input_value().strip():
                    continue
                el.click()
                el.fill(value)
                print(f"  {fid:<35} -> {value}")
                filled += 1
            except Exception as e:
                logger.debug(f"ID fill [{fid}]: {e}")
        if filled:
            print()

    # ── Phone field ───────────────────────────────────────────────────────────

    def _fill_phone(self, page, form):
        """
        Phone handling:
        - Nuro Type A: id=phone, handled by _fill_by_id
        - Waymo Type B: id=form_phone_number_X_X_X, has ITI country picker
          Must use type() with digits only to avoid country code issues
        """
        for ctx in self._ctxs(page, form):
            for inp in ctx.query_selector_all("input[type=tel]"):
                try:
                    if not inp.is_visible():
                        continue
                    fid = inp.get_attribute("id") or ""

                    # Skip standard Greenhouse phone (handled by ID fill)
                    if fid == "phone":
                        continue
                    # Skip ITI search input
                    if fid.startswith("iti-"):
                        continue

                    if inp.input_value().strip():
                        continue

                    label = self._label(ctx, inp)
                    combined = f"{fid} {label}"
                    if not re.search(r"phone|mobile|tel", combined, re.IGNORECASE):
                        continue

                    # Click and type just the 10 digits
                    inp.click()
                    inp.fill("")
                    digits = re.sub(r"[^\d]", "", P["phone"])[-10:]
                    inp.type(digits, delay=30)
                    print(f"  {fid or 'phone':<35} -> {digits}")
                    print()
                except Exception as e:
                    logger.debug(f"Phone: {e}")

    # ── Text inputs ───────────────────────────────────────────────────────────

    def _fill_text_inputs(self, page, form):
        cache = self._load_cache()
        seen = set()
        filled = 0

        for ctx in self._ctxs(page, form):
            # Standard text/email/url inputs
            for inp in ctx.query_selector_all(
                "input[type=text], input[type=email], input[type=url], input:not([type])"
            ):
                try:
                    if not inp.is_visible() or inp.is_disabled():
                        continue
                    if inp.input_value().strip():
                        continue

                    fid = inp.get_attribute("id") or ""

                    # Skip already handled fields
                    if fid in ID_FILLS:
                        continue
                    # Skip question_ fields (handled separately)
                    if fid.startswith("question_"):
                        continue
                    # Skip React Select backing inputs
                    # These have role=combobox and are controlled by React
                    role = inp.get_attribute("role") or ""
                    if role == "combobox":
                        continue
                    # Skip ITI search
                    if fid.startswith("iti-"):
                        continue

                    pos = self._pos(inp)
                    if pos in seen:
                        continue
                    seen.add(pos)

                    label = self._label(ctx, inp)
                    placeholder = (inp.get_attribute("placeholder") or "").lower()
                    combined = f"{fid} {label} {placeholder}"

                    # Cache check
                    cached = self._from_cache(label, cache)
                    if cached is not None:
                        if cached:
                            inp.click()
                            inp.fill(cached)
                            print(f"  {label[:40]:<42} -> {cached[:30]} (cached)")
                            filled += 1
                        continue

                    for pattern, value in TEXT_PATTERNS:
                        if re.search(pattern, combined, re.IGNORECASE):
                            inp.click()
                            inp.fill(value)
                            print(f"  {label[:40]:<42} -> {value}")
                            filled += 1
                            break

                except Exception as e:
                    logger.debug(f"Text input: {e}")

            # question_XXXXXXXX fields
            for inp in ctx.query_selector_all("input[type=text]"):
                try:
                    fid = inp.get_attribute("id") or ""
                    if not fid.startswith("question_") or not inp.is_visible():
                        continue
                    # Skip React Select backing inputs
                    role = inp.get_attribute("role") or ""
                    if role == "combobox":
                        continue
                    if inp.input_value().strip():
                        continue

                    pos = self._pos(inp)
                    if pos in seen:
                        continue
                    seen.add(pos)

                    label_el = ctx.query_selector(f"label[for='{fid}']")
                    label = label_el.inner_text().strip() if label_el else fid

                    answer = self._match_question(label, cache)
                    if answer is None:
                        print(f"\n  Question: {label[:80]}")
                        answer = input("  Answer (Enter to skip): ").strip()
                        if answer:
                            cache[label] = answer
                            self._save_cache(cache)
                            print("  Saved for future applications")

                    if answer:
                        inp.click()
                        inp.fill(answer)
                        print(f"  {label[:40]:<42} -> {answer[:30]}")
                        filled += 1
                except Exception as e:
                    logger.debug(f"Question: {e}")

        if filled:
            print()

    # ── Textareas ─────────────────────────────────────────────────────────────

    def _fill_textareas(self, page, form):
        seen = set()
        for ctx in self._ctxs(page, form):
            for ta in ctx.query_selector_all("textarea"):
                try:
                    if not ta.is_visible() or ta.is_disabled():
                        continue
                    fid = ta.get_attribute("id") or ""
                    if "recaptcha" in fid.lower():
                        continue
                    if ta.input_value().strip():
                        continue

                    pos = self._pos(ta)
                    if pos in seen:
                        continue
                    seen.add(pos)

                    label = self._label(ctx, ta)
                    placeholder = (ta.get_attribute("placeholder") or "").lower()
                    combined = f"{label} {placeholder}"

                    for pattern, value in TEXTAREA_PATTERNS:
                        if re.search(pattern, combined, re.IGNORECASE):
                            if value:
                                ta.click()
                                ta.fill(value)
                                print(f"  textarea '{label[:40]}' -> '{value}'")
                            break
                except Exception as e:
                    logger.debug(f"Textarea: {e}")

    # ── Native selects (Waymo) ────────────────────────────────────────────────

    def _fill_native_selects(self, ctx):
        """Fill HTML <select> elements. Label found by DOM walk."""
        filled = 0
        seen = set()

        for sel_el in ctx.query_selector_all("select"):
            try:
                if not sel_el.is_visible():
                    continue
                pos = self._pos(sel_el)
                if pos in seen:
                    continue
                seen.add(pos)

                try:
                    if sel_el.input_value().strip():
                        continue
                except Exception:
                    pass

                label_text = ctx.evaluate("""(sel) => {
                    let el = sel;
                    for (let i = 0; i < 10; i++) {
                        el = el.parentElement;
                        if (!el) break;
                        const lbl = el.querySelector('label');
                        if (lbl) return lbl.innerText.trim();
                    }
                    return '';
                }""", sel_el)

                if not label_text or label_text in ["Departments", "Locations"]:
                    continue

                answer = None
                for pattern, ans in SELECT_ANSWERS:
                    if re.search(pattern, label_text, re.IGNORECASE):
                        answer = ans
                        break
                if not answer:
                    continue

                opts = sel_el.query_selector_all("option")
                for opt in opts:
                    text = opt.inner_text().strip()
                    t_norm = text.lower().replace("\u2019", "'").replace("\u2018", "'").replace("-", " ")
                    a_norm = answer.lower().replace("\u2019", "'").replace("-", " ")
                    if a_norm[:20] in t_norm:
                        val = opt.get_attribute("value") or text
                        sel_el.select_option(value=val)
                        print(f"  {label_text[:40]:<42} -> {text[:40]}")
                        filled += 1
                        break
                else:
                    all_opts = [o.inner_text().strip() for o in opts if o.inner_text().strip()]
                    logger.debug(f"No option match: '{label_text}' answer='{answer}' opts={all_opts}")

            except Exception as e:
                logger.debug(f"Native select: {e}")

        if filled:
            print()

    # ── React selects ─────────────────────────────────────────────────────────

    def _fill_react_selects(self, ctx):
        """
        Fill Greenhouse React Select dropdowns.
        These back hidden text inputs with role=combobox.
        Structure: label → .select__control (click) → .select__option (click)

        Handles: country, gender, hispanic, veteran, disability,
                 work authorization, sponsorship (Nuro question fields)
        """
        filled = 0

        for label_el in ctx.query_selector_all("label"):
            try:
                label_text = label_el.inner_text().strip()
                if not label_text:
                    continue

                # Skip if points to a native select
                for_id = label_el.get_attribute("for") or ""
                if for_id and ctx.query_selector(f"select#{for_id}"):
                    continue

                answer = None
                for pattern, ans in REACT_SELECT_ANSWERS:
                    if re.search(pattern, label_text, re.IGNORECASE):
                        answer = ans
                        break
                if not answer:
                    continue

                # Find .select__control in parent
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

                # Already has a value?
                val_el = control.query_selector(".select__single-value")
                if val_el and val_el.inner_text().strip():
                    continue

                control.click()
                ctx.wait_for_timeout(500)

                for opt in ctx.query_selector_all("div.select__option"):
                    try:
                        text = opt.inner_text().strip()
                        t_norm = text.lower().replace("-", " ")
                        a_norm = answer.lower().replace("-", " ")
                        if a_norm[:8] in t_norm:
                            opt.click()
                            ctx.wait_for_timeout(300)
                            print(f"  {label_text[:40]:<42} -> {text}")
                            filled += 1
                            break
                    except Exception:
                        continue
                else:
                    try:
                        control.press("Escape")
                    except Exception:
                        pass

            except Exception as e:
                logger.debug(f"React select: {e}")

        if filled:
            print()

    # ── Race field ────────────────────────────────────────────────────────────

    def _fill_race(self, ctx):
        """
        Race label has no for= attribute — appears dynamically.
        Find by text content, skip if already has value.
        """
        try:
            for label_el in ctx.query_selector_all("label"):
                text = label_el.inner_text().strip().lower()
                for_id = label_el.get_attribute("for") or ""
                if ("race" in text or ("ethnicity" in text and "hispanic" not in text)) and not for_id:
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
                        return

                    val_el = control.query_selector(".select__single-value")
                    if val_el and val_el.inner_text().strip():
                        return

                    control.click()
                    ctx.wait_for_timeout(600)

                    # Prefer Asian, fall back to Decline
                    opts = ctx.query_selector_all("div.select__option")
                    for opt in opts:
                        if "asian" in opt.inner_text().lower():
                            opt.click()
                            ctx.wait_for_timeout(300)
                            print(f"  Race                                       -> {opt.inner_text().strip()}")
                            return
                    for opt in opts:
                        if "decline" in opt.inner_text().lower():
                            opt.click()
                            ctx.wait_for_timeout(300)
                            print(f"  Race                                       -> {opt.inner_text().strip()}")
                            return
        except Exception as e:
            logger.debug(f"Race: {e}")

    # ── Checkboxes ────────────────────────────────────────────────────────────

    def _fill_checkboxes(self, ctx):
        for cb in ctx.query_selector_all("input[type=checkbox]"):
            try:
                if not cb.is_visible() or cb.is_checked():
                    continue
                cb_id = cb.get_attribute("id") or ""
                label_text = ""
                if cb_id:
                    lbl = ctx.query_selector(f"label[for='{cb_id}']")
                    if lbl:
                        label_text = lbl.inner_text().lower()
                parent_text = ctx.evaluate(
                    "el => el.parentElement ? el.parentElement.innerText.toLowerCase().substring(0,100) : ''",
                    cb
                )
                combined = f"{cb_id} {label_text} {parent_text}"
                if re.search(CHECKBOX_PATTERN, combined, re.IGNORECASE):
                    cb.check()
                    short = (label_text or parent_text[:50]).strip()
                    print(f"  Checked: {short[:60]}")
            except Exception as e:
                logger.debug(f"Checkbox: {e}")

    # ── Upload resume ─────────────────────────────────────────────────────────

    _resume_uploaded = False

    def _upload_resume(self, ctx, pdf: Path):
        """
        Upload PDF resume. Use force=True to handle hidden file inputs.
        Guard against double upload with instance flag.
        """
        if self._resume_uploaded:
            return

        # Try by ID first (Type A standard)
        try:
            fi = ctx.query_selector("#resume")
            if fi:
                fi.set_input_files(str(pdf))
                print(f"  Resume uploaded: {pdf.name}")
                self._resume_uploaded = True
                return
        except Exception as e:
            logger.debug(f"Resume by id: {e}")

        # Try any file input not for cover letter
        for fi in ctx.query_selector_all("input[type=file]"):
            try:
                fid = (fi.get_attribute("id") or "").lower()
                fname = (fi.get_attribute("name") or "").lower()
                accept = (fi.get_attribute("accept") or "").lower()

                if "cover" in fid or "cover" in fname:
                    continue

                # Must accept PDF/doc (resume fields do, image fields don't)
                if accept and "pdf" not in accept and "doc" not in accept:
                    continue

                fi.set_input_files(str(pdf))
                print(f"  Resume uploaded: {pdf.name}")
                self._resume_uploaded = True
                return
            except Exception as e:
                logger.debug(f"Resume fallback: {e}")

        if not self._resume_uploaded:
            print("  Resume upload: attach manually in browser")

    # ── Review ────────────────────────────────────────────────────────────────

    def _print_review(self, page, form):
        print(f"\n{'─'*65}")
        print("  REVIEW — verify in browser before submitting")
        print(f"{'─'*65}")
        seen = set()
        for ctx in self._ctxs(page, form):
            for inp in ctx.query_selector_all(
                "input[type=text], input[type=email], input[type=tel]"
            ):
                try:
                    if not inp.is_visible():
                        continue
                    role = inp.get_attribute("role") or ""
                    if role == "combobox":
                        continue
                    pos = self._pos(inp)
                    if pos in seen:
                        continue
                    seen.add(pos)
                    fid = inp.get_attribute("id") or inp.get_attribute("name") or "?"
                    val = inp.input_value()
                    if val and val.strip():
                        print(f"  {fid[:28]:<30} {val[:40]}")
                except Exception:
                    pass
        print(f"\n  Check: All fields filled, dropdowns selected, resume attached")
        print(f"{'─'*65}\n")

    # ── Gate ──────────────────────────────────────────────────────────────────

    def _gate(self, page) -> bool:
        print("  [s] Submit   [p] Pause (fill manually)   [a] Abort\n")
        while True:
            choice = input("Choice [s/p/a]: ").strip().lower()
            if choice == "s":
                btn = None
                for frame in page.frames:
                    if "greenhouse.io/embed/job_app" in frame.url:
                        btn = self._find_submit(frame)
                        break
                if not btn:
                    btn = self._find_submit(page)
                if not btn:
                    print("Submit button not found — click manually")
                    input("Press Enter when done...")
                    return True
                try:
                    btn.scroll_into_view_if_needed()
                    page.wait_for_timeout(400)
                    url_before = page.url
                    btn.click()
                    try:
                        page.wait_for_url(lambda u: u != url_before, timeout=12000)
                        print(f"\nSubmitted! URL: {page.url}")
                    except PWTimeout:
                        body = page.inner_text("body")[:500].lower()
                        if any(w in body for w in ["thank you", "received", "success", "submitted"]):
                            print("\nSubmitted!")
                        else:
                            print("\nCheck browser — submitted?")
                            input("Press Enter when done...")
                    return True
                except Exception as e:
                    print(f"Submit error: {e} — click manually")
                    input("Press Enter when done...")
                    return True
            elif choice == "p":
                input("Browser open. Press Enter to exit...")
                return False
            elif choice == "a":
                print("Aborted.")
                return False
            else:
                print("Enter s, p, or a")

    def _find_submit(self, ctx):
        for sel in [
            "button:has-text('Submit your application')",
            "button:has-text('Submit application')",
            "button:has-text('Submit Application')",
            "button:has-text('Submit')",
            "button[type=submit]",
            "input[type=submit]",
        ]:
            try:
                btn = ctx.query_selector(sel)
                if btn and btn.is_visible():
                    return btn
            except Exception:
                pass
        return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _ctxs(self, page, form) -> list:
        return [form, page] if form is not page else [page]

    def _pos(self, el) -> tuple:
        try:
            box = el.bounding_box()
            if box:
                return (round(box["x"]), round(box["y"]))
        except Exception:
            pass
        return (id(el),)

    def _label(self, ctx, el) -> str:
        parts = []
        for attr in ["id", "name", "placeholder", "aria-label"]:
            v = el.get_attribute(attr) or ""
            if v and "recaptcha" not in v.lower() and not v.startswith("iti-"):
                parts.append(v.lower())
        try:
            fid = el.get_attribute("id")
            if fid:
                lbl = ctx.query_selector(f"label[for='{fid}']")
                if lbl:
                    parts.append(lbl.inner_text().lower())
        except Exception:
            pass
        return " ".join(parts)

    def _match_question(self, label: str, cache: dict) -> Optional[str]:
        for pattern, answer in QUESTION_ANSWERS:
            if re.search(pattern, label, re.IGNORECASE):
                return answer
        return self._from_cache(label, cache)

    def _from_cache(self, label: str, cache: dict) -> Optional[str]:
        label_lower = label.lower().strip()
        if len(label_lower) < 10:
            return None
        for cached_q, cached_a in cache.items():
            cq = cached_q.lower().strip()
            if len(cq) >= 10 and (cq[:40] in label_lower or label_lower[:40] in cq):
                return cached_a
        return None

    def _load_cache(self) -> dict:
        try:
            if QA_CACHE.exists():
                return json.loads(QA_CACHE.read_text())
        except Exception:
            pass
        return {}

    def _save_cache(self, cache: dict):
        try:
            QA_CACHE.parent.mkdir(parents=True, exist_ok=True)
            QA_CACHE.write_text(json.dumps(cache, indent=2))
        except Exception as e:
            logger.debug(f"Cache save: {e}")

    def _find_pdf(self, resume_path: Optional[Path]) -> Optional[Path]:
        if resume_path:
            p = Path(resume_path)
            if p.suffix == ".pdf" and p.exists():
                return p
            pdf = p.with_suffix(".pdf")
            if pdf.exists():
                return pdf
        main = RESUME_DIR / "Riya_Aggarwal_Resume.pdf"
        if main.exists():
            return main
        pdfs = sorted(RESUME_DIR.glob("*.pdf"),
                      key=lambda f: f.stat().st_mtime, reverse=True)
        return pdfs[0] if pdfs else None
