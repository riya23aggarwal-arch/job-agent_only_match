#!/usr/bin/env python3
"""
job_agent_sync_to_notion.py — syncs jobs.db results into your Notion Jobs Database

Run from inside job_agent/ folder:
  python job_agent_sync_to_notion.py                    # sync apply_now + review jobs
  python job_agent_sync_to_notion.py --decision apply   # sync only apply_now jobs
  python job_agent_sync_to_notion.py --decision review  # sync only review jobs
  python job_agent_sync_to_notion.py --all              # sync everything including discarded

Requires:
  pip install requests python-dotenv
  
  .env file with:
    NOTION_TOKEN=secret_xxxxx    (your Notion integration token)
    NOTION_DB_ID=xxx             (your Jobs Database ID)
  
  Get NOTION_TOKEN from: https://www.notion.so/profile/integrations
  Get NOTION_DB_ID from Jobs Database URL: notion.so/[DB_ID]?v=...
"""

import sqlite3
import json
import os
import sys
import argparse
import requests
from pathlib import Path
from datetime import datetime

# Try to load from .env, but don't fail if it doesn't exist
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Configuration
DB_PATH = os.path.join(os.path.dirname(__file__), ".job_agent", "jobs.db")
if not os.path.exists(DB_PATH):
    DB_PATH = os.path.expanduser("~/.job_agent/jobs.db")

NOTION_TOKEN = os.environ.get("NOTION_TOKEN", "")
NOTION_DB_ID = os.environ.get("NOTION_DB_ID", "f20ddf98-3453-4371-b7a2-02662dfffdac")  # Default: your Jobs DB

NOTION_API = "https://api.notion.com/v1"
HEADERS = {
    "Authorization": f"Bearer {NOTION_TOKEN}",
    "Content-Type": "application/json",
    "Notion-Version": "2022-06-28",
}


def get_jobs(decision_filter=None):
    """Fetch jobs from SQLite database."""
    if not os.path.exists(DB_PATH):
        print(f"❌ Database not found: {DB_PATH}")
        print("   Run 'python demo.py' first to create database")
        sys.exit(1)
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        if decision_filter:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE decision = ? ORDER BY created_at DESC",
                (decision_filter,)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM jobs WHERE decision IN ('apply_now', 'review') ORDER BY created_at DESC"
            ).fetchall()
    except Exception as e:
        print(f"❌ Database error: {e}")
        sys.exit(1)
    finally:
        conn.close()
    
    return [dict(r) for r in rows]


def get_existing_urls():
    """Fetch all URLs already in Notion DB to avoid duplicates."""
    existing = set()
    url = f"{NOTION_API}/databases/{NOTION_DB_ID}/query"
    body = {"page_size": 100}
    
    try:
        while True:
            r = requests.post(url, headers=HEADERS, json=body, timeout=10)
            r.raise_for_status()
            data = r.json()
            
            for page in data.get("results", []):
                props = page.get("properties", {})
                u = props.get("Apply URL", {}).get("url", "")
                if u:
                    existing.add(u)
            
            if not data.get("has_more"):
                break
            body["start_cursor"] = data["next_cursor"]
    except requests.exceptions.RequestException as e:
        print(f"⚠️  Warning: Could not fetch existing URLs: {e}")
        print("   Continuing anyway (may create duplicates)...\n")
    
    return existing


def build_notion_page(job: dict) -> dict:
    """Build Notion page properties from job dict."""
    def text(val):
        """Create rich text property."""
        val_str = str(val or "")[:2000]
        return {"rich_text": [{"text": {"content": val_str}}]} if val_str else {"rich_text": []}

    def num(val):
        """Create number property."""
        try:
            return {"number": int(val) if val is not None else None}
        except (ValueError, TypeError):
            return {"number": None}

    def select(val):
        """Create select property."""
        val_str = str(val or "").lower().replace("_", " ").title()
        return {"select": {"name": val_str}} if val_str else {"select": None}

    def date_prop(val):
        """Create date property."""
        if not val:
            return {"date": None}
        try:
            # Handle ISO format dates
            return {"date": {"start": val[:10]}}
        except (TypeError, IndexError):
            return {"date": None}

    # Build properties
    job_title = f"{job.get('company', '')} - {job.get('role', '')}"
    
    return {
        "Name": {
            "title": [{"text": {"content": job_title[:100]}}]
        },
        "Company": text(job.get("company", "")),
        "Role": text(job.get("role", "")),
        "Location": text(job.get("location", "")),
        "Score": num(job.get("score")),
        "Decision": select(job.get("decision", "skip")),
        "Status": select("shortlisted"),
        "Source": select(job.get("source", "")),
        "Apply URL": {
            "url": job.get("apply_url", "") or None
        },
        "Date Found": date_prop(job.get("date_found", "")),
        "Notes": text(f"Matched: {job.get('matched_skills', '')}\nMissing: {job.get('missing_skills', '')}"),
    }


def create_notion_page(job: dict):
    """Create a page in Notion."""
    payload = {
        "parent": {"database_id": NOTION_DB_ID},
        "properties": build_notion_page(job),
    }
    
    try:
        r = requests.post(
            f"{NOTION_API}/pages",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        
        if r.status_code == 200:
            return True, None
        else:
            error_msg = r.text
            try:
                error_msg = r.json().get("message", r.text)
            except:
                pass
            return False, error_msg
    except requests.exceptions.RequestException as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(
        description="Sync Job Agent jobs.db to Notion Jobs Database"
    )
    parser.add_argument(
        "--decision",
        choices=["apply_now", "review", "discard"],
        default=None,
        help="Sync only jobs with specific decision"
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Sync all decisions including discarded"
    )
    args = parser.parse_args()

    # Validate setup
    if not NOTION_TOKEN:
        print("❌ ERROR: NOTION_TOKEN not set")
        print()
        print("Setup instructions:")
        print("1. Get your token from: https://www.notion.so/profile/integrations")
        print("2. Create new integration (or use existing)")
        print("3. Copy the token (secret_xxxxx)")
        print()
        print("4. Create .env file in your project:")
        print("   NOTION_TOKEN=secret_xxxxx")
        print("   NOTION_DB_ID=your_database_id")
        print()
        print("5. Run sync again:")
        print("   python job_agent_sync_to_notion.py")
        sys.exit(1)

    # Get jobs
    decision = None if args.all else args.decision
    jobs = get_jobs(decision)
    
    if not jobs:
        print(f"⚠️  No jobs found to sync")
        print(f"   Decision filter: {decision or 'apply_now + review'}")
        print(f"   Database: {DB_PATH}")
        return

    print(f"🔄 Syncing {len(jobs)} jobs to Notion...")
    print()

    # Get existing jobs
    existing = get_existing_urls()
    print(f"📊 Already in Notion: {len(existing)} jobs")
    print()

    synced = 0
    skipped = 0
    failed = 0

    for i, job in enumerate(jobs, 1):
        url = job.get("apply_url", "")
        
        if url in existing:
            skipped += 1
            continue

        ok, err = create_notion_page(job)
        if ok:
            synced += 1
            company = job.get("company", "?")
            role = job.get("role", "?")
            score = job.get("score", "?")
            decision_str = job.get("decision", "?").upper().replace("_", " ")
            
            print(f"  ✅ [{decision_str:8}] {score:3}pts | {company:20} - {role}")
        else:
            failed += 1
            print(f"  ❌ FAILED: {job.get('company', '?')} - {job.get('role', '?')}")
            if err and len(err) < 200:
                print(f"     Error: {err[:100]}")

    # Summary
    print()
    print("=" * 60)
    print(f"  ✅ Synced  : {synced}")
    print(f"  ⏭️  Skipped : {skipped} (already in Notion)")
    print(f"  ❌ Failed  : {failed}")
    print("=" * 60)
    print()
    
    if synced > 0:
        print(f"✨ Jobs synced successfully!")
        print(f"📖 View in Notion: https://www.notion.so/{NOTION_DB_ID}")
        print()
    
    if failed > 0:
        print(f"⚠️  {failed} job(s) failed to sync")
        print(f"   Check your NOTION_TOKEN and database permissions")
        print()

    return synced


if __name__ == "__main__":
    main()
