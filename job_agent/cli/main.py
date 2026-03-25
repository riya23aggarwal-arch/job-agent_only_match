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
                              help="Stop after N APPLY_NOW matches (0=unlimited)"),
    parallel: bool = typer.Option(True, "--parallel/--no-parallel", "-p",
                                  help="Fetch companies in parallel (default: yes)"),
    workers: int = typer.Option(5, "--workers", "-w",
                                help="Parallel worker count (default 5)"),
    scoring_provider: Optional[str] = typer.Option(
        None, "--scoring-provider",
        help="AI scoring backend: openai | mock"),
    scoring_model: Optional[str] = typer.Option(
        None, "--scoring-model",
        help="Model name (e.g. gpt-4o-mini)"),
    save_config: bool = typer.Option(
        False, "--save-config",
        help="Save --scoring-provider/model to ~/.job_agent/config.yaml"),
    no_ai: bool = typer.Option(
        False, "--no-ai",
        help="Skip AI scoring — use keyword engine only"),
):
    """
    Collect jobs from configured sources and score them.

    \b
    SCORING:
      job-agent collect --no-ai
      job-agent collect --scoring-provider mock
      job-agent collect --scoring-provider openai --scoring-model gpt-4o-mini

    \b
    AI results are cached permanently — each job is only sent to the AI once.
    Subsequent runs use the cache instantly at zero cost.

    \b
    LIMIT counts only APPLY_NOW matches (review jobs don't count):
      job-agent collect --limit 5
    """
    setup_logging(verbose=verbose, log_to_file=not no_log)

    from job_agent.collectors.greenhouse import GreenhouseCollector, DEFAULT_COMPANIES as GH_COMPANIES
    from job_agent.collectors.lever import LeverCollector, DEFAULT_COMPANIES as LV_COMPANIES
    from job_agent.collectors.workday import WorkdayCollector, DEFAULT_WORKDAY_COMPANIES as WD_COMPANIES
    from job_agent.pipeline import Pipeline

    # ── Scorer setup ──────────────────────────────────────────────────────
    scorer = None
    if not no_ai:
        from job_agent.scoring.factory import ScorerFactory
        try:
            scorer = ScorerFactory.create_from_cli_args(
                scoring_provider=scoring_provider,
                scoring_model=scoring_model,
                interactive=(scoring_provider is None),
            )
            if save_config and scoring_provider:
                ScorerFactory.save_config(scoring_provider, scoring_model)
                console.print("[dim]💾 Scorer config saved[/dim]")
        except KeyboardInterrupt:
            console.print("\n[yellow]Scorer setup cancelled — using keyword engine.[/yellow]")
            scorer = None
        except Exception as e:
            console.print(f"[red]❌ Scorer error: {e}[/red]")
            console.print("[yellow]Falling back to keyword engine.[/yellow]")
            scorer = None

    # ── Pipeline ──────────────────────────────────────────────────────────
    db = get_db()
    pipeline = Pipeline(
        db=db,
        dry_run=dry_run,
        printer=make_printer(show_discards=verbose),
        match_limit=limit,
        workers=workers,
        scorer=scorer,
    )

    scorer_label = (
        f"[magenta]{scorer.get_name()}[/magenta]"
        if scorer else "[dim]keyword engine[/dim]"
    )
    mode_label  = "[yellow]DRY RUN[/yellow]" if dry_run else "[green]LIVE[/green]"
    limit_label = f"  |  Limit: [magenta]{limit} apply[/magenta]" if limit else ""
    par_label   = f"  |  [cyan]Parallel ({workers}w)[/cyan]" if parallel else ""

    console.print(Panel(
        f"[bold]job-agent collect[/bold]  {mode_label}\n"
        f"Sources: [cyan]{source}[/cyan]  |  Scorer: {scorer_label}"
        f"  |  Verbose: {'yes' if verbose else 'no'}{limit_label}{par_label}",
        title="🤖 Job Agent", border_style="cyan",
    ))

    # ── Run ───────────────────────────────────────────────────────────────
    all_stats = []

    if parallel:
        if source in ("greenhouse", "all"):
            all_stats.append(pipeline.run_parallel(GreenhouseCollector, GH_COMPANIES))
        if source in ("lever", "all"):
            all_stats.append(pipeline.run_parallel(LeverCollector, LV_COMPANIES))
        if source in ("workday", "all"):
            all_stats.append(pipeline.run_parallel(WorkdayCollector, WD_COMPANIES))
    else:
        collectors = []
        if source in ("greenhouse", "all"):
            collectors.append(GreenhouseCollector())
        if source in ("lever", "all"):
            collectors.append(LeverCollector())
        if source in ("workday", "all"):
            collectors.append(WorkdayCollector())
        if not collectors:
            rprint(f"[red]Unknown source: {source!r}[/red]")
            raise typer.Exit(1)
        all_stats = pipeline.run_all(collectors)

    # ── Summary table ─────────────────────────────────────────────────────
    console.print()
    table = Table(title="📊 Collection Summary", border_style="cyan")
    table.add_column("Source",       style="cyan")
    table.add_column("Fetched",      justify="right")
    table.add_column("Scored",       justify="right")
    table.add_column("✅ Apply",     justify="right", style="green")
    table.add_column("👀 Review",    justify="right", style="yellow")
    table.add_column("❌ Discarded", justify="right", style="dim")
    table.add_column("↩ Dupes",      justify="right", style="dim blue")
    table.add_column("⚠ Errors",    justify="right", style="red")
    table.add_column("♻ Cached",    justify="right", style="cyan")
    table.add_column("🪙 Tokens",    justify="right", style="magenta")
    table.add_column("⏱ Time")

    total_apply = total_review = total_tokens = total_cached = 0
    for s in all_stats:
        tok    = f"{s.tokens_used:,}" if s.tokens_used else "—"
        cached = f"{s.cache_hits}"    if s.cache_hits  else "—"
        table.add_row(
            s.source, str(s.collected), str(s.scored),
            str(s.apply_now), str(s.review), str(s.discarded),
            str(s.skipped_duplicate), str(s.errors),
            cached, tok, s.elapsed,
        )
        total_apply  += s.apply_now
        total_review += s.review
        total_tokens += s.tokens_used
        total_cached += s.cache_hits

    console.print(table)

    # Token + cost + cache summary
    if scorer:
        model_name = scoring_model or "gpt-4o-mini"
        if total_cached > 0:
            console.print(f"[cyan]♻  Cache hits: {total_cached} jobs (free)[/cyan]")
        if total_tokens > 0:
            input_tok  = int(total_tokens * 0.85)
            output_tok = int(total_tokens * 0.15)
            if "gpt-4o-mini" in model_name:
                cost = (input_tok / 1_000_000 * 0.15) + (output_tok / 1_000_000 * 0.60)
            elif "gpt-4o" in model_name:
                cost = (input_tok / 1_000_000 * 2.50) + (output_tok / 1_000_000 * 10.00)
            else:
                cost = (input_tok / 1_000_000 * 0.15) + (output_tok / 1_000_000 * 0.60)
            console.print(
                f"[magenta]🪙 New API usage: {total_tokens:,} tokens  (~${cost:.4f} USD)[/magenta]"
            )
        elif total_cached > 0:
            console.print("[dim]No new API calls — all results from cache.[/dim]")

    if dry_run:
        console.print(f"\n[yellow]⚠  DRY RUN — nothing stored.[/yellow]")
        console.print(f"   Would store: {total_apply} apply-now + {total_review} review")
        console.print("   Run without --dry-run to store.\n")
    elif total_apply + total_review > 0:
        console.print(
            f"\n[green]✅ Stored {total_apply + total_review} jobs "
            f"({total_apply} apply, {total_review} review)[/green]"
        )
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
    table.add_column("ID",     style="dim", width=14)
    table.add_column("Company",style="bold")
    table.add_column("Role")
    table.add_column("Score",  justify="right", width=6)
    table.add_column("Status", width=14)

    for j in jobs:
        sc = "green" if j.score >= 65 else "yellow" if j.score >= 35 else "red"
        table.add_row(
            j.job_id, j.company, j.role[:46],
            f"[{sc}]{j.score}[/{sc}]", j.status,
        )
    console.print(table)
    console.print("\n[dim]Run: job-agent view <ID>  to see full details[/dim]")


# ── view ───────────────────────────────────────────────────────────────────────

@app.command()
def view(job_id: str = typer.Argument(...)):
    """View full details of a stored job including AI reasoning."""
    db = get_db()
    job = db.get_job(job_id)
    if not job:
        rprint(f"[red]Job {job_id} not found[/red]"); raise typer.Exit(1)

    matched = json.loads(job.matched_skills)
    missing = json.loads(job.missing_skills)
    dc  = "green" if job.decision == "apply_now" else "yellow"
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

    # AI reasoning block
    if job.explanation and ("[OPENAI" in job.explanation or "[MOCK" in job.explanation):
        cached_marker = " [CACHED]" if "[CACHED]" in job.explanation else ""
        console.print()
        console.rule(f"[bold cyan]🤖 AI Scoring Details{cached_marker}[/bold cyan]")
        console.print()

        clean = job.explanation.replace("[CACHED]", "").strip()
        parts = clean.replace("[", "").replace("]", "").split("|")
        for part in parts:
            console.print(f"  [cyan]{part.strip()}[/cyan]")

        if matched:
            console.print()
            console.print("[bold green]✅ Why it's a match:[/bold green]")
            for r in matched[:8]:
                console.print(f"   • {r}")

        if missing:
            console.print()
            console.print("[bold yellow]⚠  Gaps / blockers:[/bold yellow]")
            for m in missing[:6]:
                console.print(f"   • {m}")
        console.print()

    # Highlighted job description
    if job.description or job.requirements:
        from job_agent.scoring.engine import HIGH_SKILL_ALIASES, MEDIUM_SKILL_ALIASES, LOW_SKILL_ALIASES
        import re

        matched_set = set(matched)
        full_text = ((job.description or "") + "\n\n" + (job.requirements or "")).strip()

        highlight_terms = []
        for skill, aliases in {**HIGH_SKILL_ALIASES, **MEDIUM_SKILL_ALIASES, **LOW_SKILL_ALIASES}.items():
            if skill in matched_set:
                highlight_terms.extend(aliases)
        highlight_terms.sort(key=len, reverse=True)

        highlighted = re.sub(r"<[^>]+>", " ", full_text)
        highlighted = re.sub(r"\s+", " ", highlighted).strip()

        for term in highlight_terms:
            pattern = re.compile(re.escape(term), re.IGNORECASE)
            highlighted = pattern.sub(
                f"[bold green on dark_green]{term}[/bold green on dark_green]",
                highlighted
            )

        console.print()
        console.rule("[bold]Full Job Description[/bold]")
        console.print()
        console.print(highlighted)
        console.print()


# ── cache-stats ────────────────────────────────────────────────────────────────

@app.command(name="cache-stats")
def cache_stats():
    """Show AI scoring cache statistics."""
    try:
        from job_agent.scoring.ai_cache import AICache
        cache = AICache()
        stats = cache.stats()

        console.print(Panel(
            f"[bold]Total cached:[/bold] {stats['total_cached']} jobs\n"
            f"[bold]Tokens saved:[/bold] {stats.get('total_tokens_saved', 0):,} "
            f"(~${stats.get('total_tokens_saved', 0) / 1_000_000 * 0.15:.4f} USD)\n"
            f"[bold]Cache file:[/bold]   {stats['db_path']}",
            title="♻  AI Score Cache", border_style="cyan",
        ))

        if stats.get("by_provider"):
            table = Table(border_style="dim")
            table.add_column("Provider")
            table.add_column("Model")
            table.add_column("Cached jobs", justify="right")
            for row in stats["by_provider"]:
                table.add_row(row["provider"], row["model"] or "—", str(row["cnt"]))
            console.print(table)

    except Exception as e:
        rprint(f"[red]Could not read cache: {e}[/red]")



# ── dashboard ──────────────────────────────────────────────────────────────────

@app.command()
def dashboard(
    port: int = typer.Option(5000, "--port", "-p", help="Port to serve on"),
    no_browser: bool = typer.Option(False, "--no-browser", help="Don't auto-open browser"),
):
    """Launch the web dashboard at http://localhost:5000"""
    try:
        from job_agent.dashboard import run
        run(port=port, open_browser=not no_browser)
    except ImportError:
        rprint("[red]Flask not installed. Run: pip install flask[/red]")
        raise typer.Exit(1)

# ── Entry point ────────────────────────────────────────────────────────────────

def main():
    app()


if __name__ == "__main__":
    main()
