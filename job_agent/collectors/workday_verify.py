#!/usr/bin/env python3
"""
Workday config verifier — find the correct tenant/site for any company.

Usage:
  # Find config for a specific company
  python workday_verify.py --company cisco

  # Test a specific config
  python workday_verify.py --company cisco --wd 5 --site External

  # Test all currently configured companies
  python workday_verify.py --all
"""

import sys
import time
import argparse
import requests
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

# Common site names to try
COMMON_SITES = [
    "External",
    "Careers",
    "Jobs",
    "Global",
    "US",
    "NVIDIAExternalCareerSite",
    "CiscoExternalSite",
    "AWSExternalSite",
]

COMMON_WD_NUMS = [1, 2, 3, 5]


def test_config(tenant: str, wd_num: int, site: str, keyword: str = "engineer") -> dict:
    url = f"https://{tenant}.wd{wd_num}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    payload = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": keyword}

    try:
        resp = requests.post(url, json=payload, headers=HEADERS, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("total", len(data.get("jobPostings", [])))
            return {"status": "ok", "total": total, "url": url}
        return {"status": f"http_{resp.status_code}", "url": url}
    except requests.Timeout:
        return {"status": "timeout", "url": url}
    except Exception as e:
        return {"status": f"error: {str(e)[:50]}", "url": url}


def find_config(tenant: str):
    """Try all combinations to find a working config."""
    print(f"\nSearching for working Workday config: {tenant}")
    print("─" * 60)

    found = []
    for wd_num in COMMON_WD_NUMS:
        for site in COMMON_SITES:
            result = test_config(tenant, wd_num, site)
            status = result["status"]
            if status == "ok":
                total = result["total"]
                print(f"  ✅ FOUND!  wd{wd_num} / {site:<35} → {total} jobs")
                found.append((tenant, wd_num, site, total))
            elif status == "http_404":
                print(f"  ❌ 404     wd{wd_num} / {site}")
            elif status == "http_422":
                print(f"  ⚠  422     wd{wd_num} / {site}  (wrong payload format)")
            else:
                print(f"  ⚠  {status[:20]:<20} wd{wd_num} / {site}")
            time.sleep(0.3)

    if found:
        print(f"\n✅ Working configs found for '{tenant}':")
        for t, w, s, total in found:
            print(f'  ("{t}", {w}, "{s}", "{t.capitalize()}"),  # {total} jobs')
        print(f"\nAdd the best one to DEFAULT_WORKDAY_COMPANIES in workday.py")
    else:
        print(f"\n❌ No working config found for '{tenant}'")
        print(f"   Try visiting {tenant}.com/careers and checking the job URL")
        print(f"   Look for: {tenant}.wd?.myworkdayjobs.com/en-US/<SITE_NAME>/job/...")

    return found


def test_all():
    """Test all currently configured companies."""
    sys.path.insert(0, str(Path(__file__).parent.parent.parent))
    from job_agent.collectors.workday import DEFAULT_WORKDAY_COMPANIES

    print(f"\nTesting {len(DEFAULT_WORKDAY_COMPANIES)} configured companies...")
    print("─" * 60)

    working = []
    broken  = []

    for tenant, wd_num, site, display in DEFAULT_WORKDAY_COMPANIES:
        result = test_config(tenant, wd_num, site)
        status = result["status"]
        if status == "ok":
            print(f"  ✅ {display:<20} wd{wd_num}/{site:<30} → {result['total']} jobs")
            working.append(display)
        else:
            print(f"  ❌ {display:<20} wd{wd_num}/{site:<30} → {status}")
            broken.append(display)
        time.sleep(0.3)

    print(f"\nResults: {len(working)} working, {len(broken)} broken")
    if broken:
        print(f"Broken: {', '.join(broken)}")
        print("Run: python workday_verify.py --company <name>  to find correct config")


def main():
    parser = argparse.ArgumentParser(description="Verify Workday company configs")
    parser.add_argument("--company", help="Company tenant name to search (e.g. cisco, nvidia)")
    parser.add_argument("--wd",      type=int, help="Workday number (1-5)")
    parser.add_argument("--site",    help="Site name (e.g. External, Careers)")
    parser.add_argument("--all",     action="store_true", help="Test all configured companies")
    args = parser.parse_args()

    if args.all:
        test_all()
    elif args.company and args.wd and args.site:
        result = test_config(args.company, args.wd, args.site)
        if result["status"] == "ok":
            print(f"✅ Working! {result['total']} jobs found")
            print(f'   Add to workday.py: ("{args.company}", {args.wd}, "{args.site}", "{args.company.capitalize()}"),')
        else:
            print(f"❌ Failed: {result['status']}")
    elif args.company:
        find_config(args.company)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
