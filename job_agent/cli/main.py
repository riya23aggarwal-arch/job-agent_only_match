"""
job-agent CLI — all commands
"""

import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich import print as rprint

app = typer.Typer(name="job-agent", help="Riya's job pipeline", add_completion=False)
console = Console()
LOG_DIR = Path.home() / ".job_agent" / "logs"


def get_db():
    from job_agent.storage.database import Database
    return Database()


def setup_logging(verbose: bool = False, log_to_file: bool = True):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

    handlers = [RichHandler(console=console, show_time=True, show_path=False, rich_tracebacks=True)]

    if log_to_file:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        handlers.append(fh)

    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(message)s",
        datefmt="[%H:%M:%S]",
        handlers=handlers,
        force=True,
    )

    if log_to_file:
        console.print(f"[dim]📝 Logging to {log_file}[/dim]")
    return log_file


def make_printer(show_discards: bool):
    """Rich-formatted printer injected into the pipeline."""
    def printer(level: str, msg: str):
        if level == "header":
            console.rule(f"[bold cyan]{msg}[/bold cyan]")
        elif level == "apply":
            console.print(f"[bold green]{msg}[/bold green]")
        elif level == "skills":
            console.print(f"[dim green]{msg}[/dim green]")
        elif level == "review":
            console.print(f"[bold yellow]{msg}[/bold yellow]")
        elif level == "discard":
            if show_discards:
                console.print(f"[dim]{msg}[/dim]")
        elif level == "dupe":
            if show_discards:
                console.print(f"[dim blue]{msg}[/dim blue]")
        elif level == "counter":
            console.rule(f"[cyan]{msg}[/cyan]")
        elif level == "error":
            console.print(f"[bold red]{msg}[/bold red]")
        elif level == "summary":
            console.print(f"\n[bold]{msg}[/bold]")
        logging.getLogger("pipeline.file").info(msg)
    return printer


# ── collect ────────────────────────────────────────────────────────────────────

@app.command()
def collect(
    source: str = typer.Option("all", "--source", "-s",
                               help="greenhouse | lever | workday | all"),
    dry_run: bool = typer.Option(False, "--dry-run",
                                 help="Score but don't store anything"),
    verbose: bool = typer.Option(False, "--verbose", "-v",
                                 help="Show discards and dupes"),
    no_log: bool = typer.Option(False, "--no-log"),
    limit: int = typer.Option(0, "--limit", "-l",
                              help="Stop after N matches (0=unlimited)"),
    parallel: bool = typer.Option(False, "--parallel", "-p",
                                  help="Fetch companies in parallel (faster)"),
    workers: int = typer.Option(5, "--workers", "-w",
                                help="Parallel worker count (default 5)"),
):
    """Collect jobs from configured sources and run the scoring pipeline."""
    setup_logging(verbose=verbose, log_to_file=not no_log)

    from job_agent.collectors.greenhouse import GreenhouseCollector, DEFAULT_COMPANIES as GH_COMPANIES
    from job_agent.collectors.lever import LeverCollector, DEFAULT_COMPANIES as LV_COMPANIES
    from job_agent.collectors.workday import WorkdayCollector, DEFAULT_WORKDAY_COMPANIES as WD_COMPANIES
    from job_agent.pipeline import Pipeline

    db = get_db()
    pipeline = Pipeline(
        db=db,
        dry_run=dry_run,
        printer=make_printer(show_discards=verbose),
        match_limit=limit,
        workers=workers,
    )

    mode_label = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    limit_label = f"  |  Limit: [magenta]{limit}[/magenta]" if limit else ""
    par_label = f"  |  [cyan]Parallel ({workers}w)[/cyan]" if parallel else ""
    console.print(Panel(
        f"[bold]job-agent collect[/bold]  {mode_label}\n"
        f"Sources: [cyan]{source}[/cyan]  |  "
        f"Verbose: {'yes' if verbose else 'no'}{limit_label}{par_label}",
        title="🤖 Job Agent", border_style="cyan",
    ))

    all_stats = []

    if parallel:
        # Parallel mode — fetch all companies of a source simultaneously
        if source in ("greenhouse", "all"):
            all_stats.append(pipeline.run_parallel(GreenhouseCollector, GH_COMPANIES))
        if source in ("lever", "all"):
            all_stats.append(pipeline.run_parallel(LeverCollector, LV_COMPANIES))
        if source in ("workday", "all"):
            all_stats.append(pipeline.run_parallel(WorkdayCollector, WD_COMPANIES))
    else:
        # Sequential mode
        collectors = []
        if source in ("greenhouse", "all"):
            collectors.append(GreenhouseCollector())
        if source in ("lever", "all"):
            collectors.append(LeverCollector())
        if source in ("workday", "all"):
            collectors.append(WorkdayCollector())
        if not collectors:
            rprint(f"[red]Unknown source: {source}[/red]")
            raise typer.Exit(1)
        all_stats = pipeline.run_all(collectors)

    # Summary table
    console.print()
    table = Table(title="📊 Collection Summary", border_style="cyan")
    table.add_column("Source", style="cyan")
    table.add_column("Fetched", justify="right")
    table.add_column("Scored", justify="right")
    table.add_column("✅ Apply", justify="right", style="green")
    table.add_column("👀 Review", justify="right", style="yellow")
    table.add_column("❌ Discarded", justify="right", style="dim")
    table.add_column("↩ Dupes", justify="right", style="dim blue")
    table.add_column("⚠ Errors", justify="right", style="red")
    table.add_column("⏱ Time")

    total_apply = total_review = 0
    for s in all_stats:
        table.add_row(
            s.source, str(s.collected), str(s.scored),
            str(s.apply_now), str(s.review), str(s.discarded),
            str(s.skipped_duplicate), str(s.errors), s.elapsed,
        )
        total_apply += s.apply_now
        total_review += s.review

    console.print(table)

    if dry_run:
        console.print(f"\n[yellow]⚠  DRY RUN — nothing stored.[/yellow]")
        console.print(f"   Would store: {total_apply} apply-now + {total_review} review")
        console.print("   Run without --dry-run to store.\n")
    elif total_apply + total_review > 0:
        console.print(f"\n[green]✅ Stored {total_apply + total_review} jobs "
                      f"({total_apply} apply, {total_review} review)[/green]")
        console.print("   Run [bold]job-agent shortlist[/bold] to see them.\n")
    else:
        console.print("\n[dim]No new matches this run.[/dim]\n")


# ── score ──────────────────────────────────────────────────────────────────────

@app.command()
def score(
    url: Optional[str] = typer.Option(None, "--url"),
    text: Optional[str] = typer.Option(None, "--text"),
    company: str = typer.Option("Unknown", "--company"),
    role: str = typer.Option("Unknown", "--role"),
):
    """Score a single job against your profile."""
    from job_agent.models import RawJob
    from job_agent.scoring.engine import ScoringEngine, SCORE_APPLY_NOW, SCORE_REVIEW

    if url:
        import requests
        from bs4 import BeautifulSoup
        try:
            resp = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
            content = BeautifulSoup(resp.text, "html.parser").get_text("\n")[:4000]
        except Exception as e:
            rprint(f"[red]Could not fetch: {e}[/red]"); raise typer.Exit(1)
    elif text:
        content = text
    else:
        rprint("[red]Provide --url or --text[/red]"); raise typer.Exit(1)

    job = RawJob(company=company, role=role, location="",
                 description=content, requirements="", apply_url=url or "", source="manual")
    result = ScoringEngine().score(job)
    color = "green" if result.score >= SCORE_APPLY_NOW else "yellow" if result.score >= SCORE_REVIEW else "red"

    console.print(Panel(
        f"[bold {color}]{result.score}/100 — {result.decision.value.upper()}[/bold {color}]\n\n"
        f"[bold]Matched:[/bold] {', '.join(result.matched_skills) or 'None'}\n"
        f"[bold]Missing:[/bold] {', '.join(result.missing_skills[:6]) or 'None'}\n\n"
        f"[dim]{result.explanation}[/dim]",
        title=f"Score: {company} — {role}", border_style=color,
    ))


# ── shortlist ──────────────────────────────────────────────────────────────────

@app.command()
def shortlist(
    decision: Optional[str] = typer.Option(None, "--decision", "-d"),
    min_score: int = typer.Option(0, "--min-score"),
    status: Optional[str] = typer.Option(None, "--status"),
):
    """Show shortlisted jobs ranked by score."""
    db = get_db()
    jobs = db.get_all_jobs(decision=decision, status=status, min_score=min_score)

    if not jobs:
        rprint("[yellow]No jobs found.[/yellow]")
        rprint("Run [bold]job-agent collect[/bold] first.")
        return

    table = Table(title=f"🎯 Shortlisted Jobs ({len(jobs)})", border_style="cyan", expand=True)
    table.add_column("ID", style="dim", width=14)
    table.add_column("Company", style="bold")
    table.add_column("Role")
    table.add_column("Score", justify="right", width=6)
    table.add_column("Status", width=14)
    table.add_column("Action", width=12)

    for j in jobs:
        dc = "green" if j.decision == "apply_now" else "yellow"
        sc = "green" if j.score >= 65 else "yellow" if j.score >= 35 else "red"
        action = f"[bold green][a]{j.job_id[:8]}[/a][/bold green]" if j.status != "applied" else "[dim]applied[/dim]"
        
        table.add_row(
            j.job_id, j.company, j.role[:42],
            f"[{sc}]{j.score}[/{sc}]", j.status, action,
        )
    console.print(table)
    
    console.print("\n[dim]Usage: job-agent apply <ID>  |  job-agent tailor <ID>  |  job-agent view <ID>[/dim]")
    
    # Interactive menu
    while True:
        choice = input("\nEnter job ID to apply/tailor or 'q' to quit: ").strip()
        if choice.lower() == 'q':
            break
        if choice:
            # Try original case first, then uppercase
            job = db.get_job(choice)
            if not job:
                job = db.get_job(choice.upper())
            if not job:
                rprint(f"[red]Job not found: {choice}[/red]")
                continue
            
            action = input(f"(a)pply, (t)ailor, (v)iew, or (q)uit? ").strip().lower()
            if action == 'a':
                from job_agent.apply.engine import ApplyContext, ApplyEngine
                resume_path = Path(job.tailored_resume_path) if job.tailored_resume_path else None
                ctx = ApplyContext(job=job, resume_path=resume_path, cover_letter_path=None, mode="assisted")
                if ApplyEngine().run(ctx):
                    db.mark_applied(job.job_id, "Applied via shortlist")
                    console.print(f"[green]✅ Applied: {job.company} — {job.role}[/green]")
            elif action == 't':
                console.print(f"[cyan]Generating tailored resume...[/cyan]")
                os.system(f"job-agent tailor {job.job_id}")
            elif action == 'v':
                os.system(f"job-agent view {job.job_id}")


# ── view ───────────────────────────────────────────────────────────────────────

@app.command()
def view(job_id: str = typer.Argument(...)):
    """View full detail of a job."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)

    matched = json.loads(job.matched_skills)
    missing = json.loads(job.missing_skills)
    dc = "green" if job.decision == "apply_now" else "yellow"
    bar = "█" * (job.score // 5) + "░" * (20 - job.score // 5)

    console.print(Panel(
        f"[bold]{job.company}[/bold] — {job.role}\n"
        f"📍 {job.location}  |  Source: {job.source}  |  Found: {job.date_found[:10]}\n\n"
        f"Score: [{dc}]{job.score}/100[/{dc}]  [{bar}]  Decision: [{dc}]{job.decision.upper()}[/{dc}]\n"
        f"Status: [bold]{job.status}[/bold]\n\n"
        f"[green]Matched:[/green] {', '.join(matched) or 'None'}\n"
        f"[red]Missing:[/red]  {', '.join(missing) or 'None'}\n\n"
        f"[dim]{job.explanation}[/dim]\n\n🔗 {job.apply_url}",
        title=f"Job {job_id}", border_style=dc,
    ))
    # Show full description with matched skills highlighted
    if job.description or job.requirements:
        from job_agent.scoring.engine import HIGH_SKILL_ALIASES, MEDIUM_SKILL_ALIASES, LOW_SKILL_ALIASES
        import re

        matched = set(json.loads(job.matched_skills))
        full_text = ((job.description or "") + "\n\n" + (job.requirements or "")).strip()

        # Build a highlighted version — wrap matched terms in rich markup
        highlighted = full_text
        # Collect all alias terms for matched skills
        highlight_terms = []
        for skill, aliases in {**HIGH_SKILL_ALIASES, **MEDIUM_SKILL_ALIASES, **LOW_SKILL_ALIASES}.items():
            if skill in matched:
                for alias in aliases:
                    highlight_terms.append(alias)

        # Sort longest first to avoid partial replacements
        highlight_terms.sort(key=len, reverse=True)

        # Strip HTML tags first
        highlighted = re.sub(r"<[^>]+>", " ", highlighted)
        highlighted = re.sub(r"\s+", " ", highlighted).strip()

        # Apply highlights — replace matched terms with [bold green]term[/bold green]
        highlighted_rich = highlighted
        for term in highlight_terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted_rich = pattern.sub(
                f"[bold green on dark_green]{term}[/bold green on dark_green]",
                highlighted_rich
            )

        console.print()
        console.rule("[bold]Full Job Description[/bold]")
        console.print()
        console.print(highlighted_rich)
        console.print()
        console.rule(f"[dim]Matched skills highlighted in green[/dim]")


# ── tailor ─────────────────────────────────────────────────────────────────────

@app.command()
def tailor(
    job_id: str = typer.Argument(...),
    fmt: str = typer.Option("markdown", "--format", "-f", help="markdown | text | latex"),
):
    """Generate tailored resume for a job."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)
    with console.status(f"[cyan]Tailoring for {job.company}...[/cyan]"):
        from job_agent.resume.tailor import ResumeTailor
        path = ResumeTailor().tailor(job, fmt=fmt)
        db.update_resume_path(job_id, str(path))
    console.print(f"[green]✅ Saved:[/green] {path}")


# ── cover-letter ───────────────────────────────────────────────────────────────

@app.command(name="cover-letter")
def cover_letter(job_id: str = typer.Argument(...)):
    """Generate cover letter, recruiter email, and Q&A."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)
    with console.status(f"[cyan]Generating for {job.company}...[/cyan]"):
        from job_agent.cover_letter.generator import CoverLetterGenerator
        paths = CoverLetterGenerator().generate_all(job)
        if paths.get("cover_letter"):
            db.update_cover_letter_path(job_id, str(paths["cover_letter"]))
    t = Table(title="📝 Generated", border_style="green")
    t.add_column("Document"); t.add_column("Path")
    for doc_type, path in paths.items():
        t.add_row(doc_type.replace("_", " ").title(), str(path))
    console.print(t)


# ── apply ──────────────────────────────────────────────────────────────────────

@app.command()
def apply(
    job_id: str = typer.Argument(...),
    mode: str = typer.Option("assisted", "--mode", "-m", help="assisted | semi_auto"),
):
    """Playwright-assisted apply. Always pauses before submit."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)
    
    from job_agent.apply.engine import ApplyContext, ApplyEngine
    
    # ✅ REQUIRE RESUME BEFORE APPLYING
    resume_path = None
    if job.tailored_resume_path and Path(job.tailored_resume_path).exists():
        resume_path = Path(job.tailored_resume_path)
    
    if not resume_path:
        console.print(f"[red]❌ No tailored resume found[/red]")
        console.print(f"[yellow]   Run: job-agent tailor {job_id}[/yellow]")
        raise typer.Exit(1)
    
    # ✅ LOAD Q&A ANSWERS FROM FILE
    cover_letter_path = None
    qa_answers = None
    
    if job.cover_letter_path and Path(job.cover_letter_path).exists():
        cover_letter_path = Path(job.cover_letter_path)
        # Try to load Q&A answers
        try:
            qa_file = Path.home() / ".job_agent" / "cover_letters" / f"qa_answers_{job_id}_*.md"
            import glob
            qa_files = glob.glob(str(qa_file))
            if qa_files:
                qa_content = Path(qa_files[0]).read_text()
                qa_answers = _parse_qa_file(qa_content)
        except Exception as e:
            logger.debug(f"Could not load Q&A answers: {e}")
    
    ctx = ApplyContext(
        job=job, 
        resume_path=resume_path, 
        cover_letter_path=cover_letter_path,
        qa_answers=qa_answers,
        mode=mode
    )
    
    engine = ApplyEngine()
    if engine.run(ctx):
        db.mark_applied(job_id, "Applied via job-agent")
        console.print(f"[green]✅ Applied: {job.company} — {job.role}[/green]")


def _parse_qa_file(content: str) -> dict:
    """Parse Q&A markdown file into structured dict."""
    import re
    answers = {}
    sections = re.split(r"^##\s+", content, flags=re.MULTILINE)[1:]
    
    for section in sections:
        lines = section.split("\n", 1)
        if len(lines) < 2:
            continue
        
        question_title = lines[0].strip().lower()
        answer_text = lines[1].strip()
        
        if "why this role" in question_title or ("why" in question_title and "role" in question_title):
            answers["why_role"] = answer_text
        elif "why this company" in question_title or ("why" in question_title and "company" in question_title):
            answers["why_company"] = answer_text
        elif "relevant" in question_title or "experience" in question_title:
            answers["relevant_exp"] = answer_text
        elif "strength" in question_title:
            answers["strengths"] = answer_text
        elif "challenge" in question_title or "debug" in question_title:
            answers["challenge"] = answer_text
    
    return answers if answers else None


# ── track ──────────────────────────────────────────────────────────────────────

@app.command()
def track(
    job_id: str = typer.Argument(...),
    status: str = typer.Option(..., "--status", "-s",
                               help="shortlisted|ready_to_apply|applied|interview|rejected|offer"),
    notes: str = typer.Option("", "--notes", "-n"),
):
    """Update application status."""
    from job_agent.models import ApplicationStatus
    valid = [s.value for s in ApplicationStatus]
    if status not in valid:
        rprint(f"[red]Invalid. Choose: {', '.join(valid)}[/red]"); raise typer.Exit(1)
    db = get_db()
    if not db.get_job(job_id):
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)
    db.update_status(job_id, status, notes)
    console.print(f"[green]✅[/green]  {job_id}  →  [bold]{status}[/bold]")
    if notes:
        console.print(f"[dim]   {notes}[/dim]")


# ── export ─────────────────────────────────────────────────────────────────────

@app.command()
def export(
    output: str = typer.Option("jobs_export.csv", "--output", "-o"),
    decision: Optional[str] = typer.Option(None, "--decision"),
):
    """Export jobs to CSV."""
    import csv
    db = get_db()
    jobs = db.get_all_jobs(decision=decision)
    if not jobs:
        rprint("[yellow]No jobs to export.[/yellow]"); return
    path = Path(output)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["job_id","company","role","location","score","decision",
                    "status","date_found","date_applied","apply_url","notes"])
        for j in jobs:
            w.writerow([j.job_id,j.company,j.role,j.location,j.score,j.decision,
                        j.status,j.date_found,j.date_applied or "",j.apply_url,j.notes])
    console.print(f"[green]✅ Exported {len(jobs)} jobs → {path}[/green]")


# ── qa-list ───────────────────────────────────────────────────────────────────

@app.command(name="qa-list")
def qa_list():
    """View all saved Q&A pairs from database."""
    db = get_db()
    qa_pairs = db.list_qa()
    
    if not qa_pairs:
        rprint("[yellow]No Q&A pairs saved yet.[/yellow]")
        return
    
    table = Table(title=f"💾 Saved Q&A Database ({len(qa_pairs)})", border_style="cyan")
    table.add_column("Question", style="bold")
    table.add_column("Answer")
    table.add_column("Used", justify="right")
    
    for qa in qa_pairs:
        q_preview = qa["question"][:60]
        a_preview = qa["answer"][:50].replace("\n", " ")
        table.add_row(q_preview, a_preview, str(qa["frequency"]))
    
    console.print(table)


# ── clean ──────────────────────────────────────────────────────────────────────

@app.command()
def clean(
    jobs: bool = typer.Option(False, "--jobs", help="Remove all jobs from database"),
    resumes: bool = typer.Option(False, "--resumes", help="Remove tailored resumes"),
    letters: bool = typer.Option(False, "--letters", help="Remove cover letters"),
    logs: bool = typer.Option(False, "--logs", help="Remove logs"),
    qa: bool = typer.Option(False, "--qa", help="Remove Q&A database"),
    all: bool = typer.Option(False, "--all", help="Remove everything"),
):
    """Clean up data."""
    if not any([jobs, resumes, letters, logs, qa, all]):
        rprint("[yellow]Usage: job-agent clean --jobs|--resumes|--letters|--logs|--qa|--all[/yellow]")
        return
    
    db_path = Path.home() / ".job_agent" / "jobs.db"
    resumes_dir = Path.home() / ".job_agent" / "resumes"
    letters_dir = Path.home() / ".job_agent" / "cover_letters"
    logs_dir = Path.home() / ".job_agent" / "logs"
    
    if all:
        if typer.confirm("Remove ALL data (.job_agent folder)?"):
            import shutil
            shutil.rmtree(Path.home() / ".job_agent", ignore_errors=True)
            console.print("[green]✅ Cleaned all data[/green]")
        return
    
    if jobs:
        if typer.confirm(f"Remove all jobs from database?"):
            db_path.unlink(missing_ok=True)
            console.print("[green]✅ Removed jobs[/green]")
    
    if resumes:
        if typer.confirm(f"Remove all tailored resumes?"):
            for f in resumes_dir.glob("resume_*.md"):
                f.unlink(missing_ok=True)
            for f in resumes_dir.glob("resume_*.pdf"):
                f.unlink(missing_ok=True)
            console.print("[green]✅ Removed tailored resumes[/green]")
    
    if letters:
        if typer.confirm(f"Remove all cover letters?"):
            for f in letters_dir.glob("*"):
                f.unlink(missing_ok=True)
            console.print("[green]✅ Removed cover letters[/green]")
    
    if logs:
        if typer.confirm(f"Remove all logs?"):
            for f in logs_dir.glob("*"):
                f.unlink(missing_ok=True)
            console.print("[green]✅ Removed logs[/green]")
    
    if qa:
        if typer.confirm(f"Remove Q&A database?"):
            db = get_db()
            db._conn().execute("DELETE FROM question_answers")
            db._conn().commit()
            console.print("[green]✅ Removed Q&A database[/green]")



@app.command()
def stats():
    """Pipeline and application statistics."""
    db = get_db()
    s = db.get_stats()
    console.print(Panel(
        f"[bold]Total stored:[/bold]    {s['total_stored']}\n"
        f"[bold]Total discarded:[/bold] {s['discarded_total']}\n"
        f"[bold]Average score:[/bold]   {s['average_score']}",
        title="📊 Stats", border_style="cyan",
    ))
    for title, key in [("By Decision", "by_decision"), ("By Status", "by_status")]:
        if s.get(key):
            t = Table(title=title, border_style="dim")
            t.add_column("Label"); t.add_column("Count", justify="right")
            for k, v in s[key].items():
                color = "green" if k == "apply_now" else "yellow" if k == "review" else "dim"
                t.add_row(f"[{color}]{k}[/{color}]", str(v))
            console.print(t)
    logs = sorted(LOG_DIR.glob("*.log")) if LOG_DIR.exists() else []
    if logs:
        console.print(f"\n[dim]📝 {len(logs)} log(s) in {LOG_DIR}\n   Latest: {logs[-1].name}[/dim]")


# ── debug-job ──────────────────────────────────────────────────────────────────

@app.command(name="debug-job")
def debug_job(job_id: str = typer.Argument(...)):
    """Full skill match breakdown for a stored job."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)

    from job_agent.scoring.engine import (
        HIGH_SKILL_ALIASES, MEDIUM_SKILL_ALIASES, LOW_SKILL_ALIASES,
        ANTI_SKILL_ALIASES, SCORE_APPLY_NOW, SCORE_REVIEW, ScoringEngine,
    )
    from job_agent.models import RawJob
    import re

    raw = RawJob(company=job.company, role=job.role, location=job.location,
                 description=job.description, requirements=job.requirements,
                 apply_url=job.apply_url, source=job.source)
    result = ScoringEngine().score(raw)
    text = (job.role + " " + job.description + " " + job.requirements).lower()
    dc = "green" if result.score >= SCORE_APPLY_NOW else "yellow" if result.score >= SCORE_REVIEW else "red"

    console.print(Panel(
        f"[bold]{job.company}[/bold] — {job.role}\n"
        f"Score: [{dc}]{result.score}/100[/{dc}]  Decision: [{dc}]{result.decision.value.upper()}[/{dc}]",
        title=f"🔍 Debug: {job_id}", border_style=dc,
    ))

    def show_skills(alias_map, label, weight, color):
        t = Table(title=f"{label} (+{weight} each)", border_style="dim")
        t.add_column("Skill", width=25); t.add_column("Status", width=10)
        t.add_column("Matched term", width=35); t.add_column("Pts", justify="right", width=5)
        for canonical, aliases in alias_map.items():
            matched = next(
                (a for a in aliases if (a in text if " " in a else
                 re.search(r"\b" + re.escape(a.lower()) + r"\b", text))), None
            )
            if matched:
                t.add_row(f"[{color}]{canonical}[/{color}]", f"[{color}]✅[/{color}]",
                          f"[dim]{matched}[/dim]", f"[{color}]+{weight}[/{color}]")
            else:
                t.add_row(f"[dim]{canonical}[/dim]", "[dim]❌[/dim]",
                          f"[dim]{', '.join(aliases[:2])}...[/dim]", "[dim]0[/dim]")
        console.print(t)

    show_skills(HIGH_SKILL_ALIASES,   "🔴 HIGH",   10, "green")
    show_skills(MEDIUM_SKILL_ALIASES, "🟡 MEDIUM",  5, "yellow")

    t2 = Table(title="🚫 Anti-Skills", border_style="dim")
    t2.add_column("Skill", width=25); t2.add_column("Status", width=12)
    t2.add_column("Term", width=30); t2.add_column("Pts", justify="right")
    for canonical, aliases in ANTI_SKILL_ALIASES.items():
        matched = next(
            (a for a in aliases if (a in text if " " in a else
             re.search(r"\b" + re.escape(a.lower()) + r"\b", text))), None
        )
        if matched:
            t2.add_row(f"[red]{canonical}[/red]", "[red]⚠ HIT[/red]",
                       f"[dim]{matched}[/dim]", "[red]-15[/red]")
        else:
            t2.add_row(f"[dim]{canonical}[/dim]", "[dim green]✓[/dim green]", "", "[dim]0[/dim]")
    console.print(t2)

    t3 = Table(title="📊 Score Breakdown", border_style="cyan")
    t3.add_column("Component"); t3.add_column("Points", justify="right")
    for k, v in result.skill_breakdown.items():
        c = "green" if v > 0 else "red" if v < 0 else "dim"
        t3.add_row(k.replace("_", " ").title(), f"[{c}]{v:+d}[/{c}]")
    console.print(t3)


# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app()


if __name__ == "__main__":
    main()
