#!/usr/bin/env python3
"""
Run all job-agent tests.

Usage:
    python run_tests.py
    python run_tests.py --verbose
"""

import sys
import os
import argparse
import importlib
import traceback
from pathlib import Path

# Make sure job_agent is importable from project root
sys.path.insert(0, str(Path(__file__).parent.parent))

SUITES = [
    ("Scoring Engine",       "job_agent.tests.test_scoring"),
    ("Database Layer",       "job_agent.tests.test_database"),
    ("Pipeline Integration", "job_agent.tests.test_pipeline"),
]


def run_suite(suite_name: str, module_path: str, verbose: bool) -> tuple[int, int]:
    """Import and run all test_ functions in a module. Returns (passed, failed)."""
    print(f"\n{'─'*60}")
    print(f"  {suite_name}")
    print(f"{'─'*60}")

    try:
        mod = importlib.import_module(module_path)
    except ImportError as e:
        print(f"  ✗ Could not import {module_path}: {e}")
        return 0, 1

    tests = [
        (name, fn)
        for name, fn in vars(mod).items()
        if name.startswith("test_") and callable(fn)
    ]

    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
            if verbose:
                print(f"  ✓ {name}")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAIL  {name}")
            print(f"         {e}")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR {name}")
            if verbose:
                traceback.print_exc()
            else:
                print(f"         {type(e).__name__}: {e}")
            failed += 1

    status = "✓ ALL PASSED" if failed == 0 else f"✗ {failed} FAILED"
    print(f"\n  {status} ({passed} passed, {failed} failed)")
    return passed, failed


def main():
    parser = argparse.ArgumentParser(description="Run job-agent test suites")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show each test name")
    parser.add_argument("--suite", "-s", choices=["scoring", "database", "pipeline"],
                        help="Run only one suite")
    args = parser.parse_args()

    suites = SUITES
    if args.suite:
        suites = [(n, m) for n, m in SUITES if args.suite in m]

    print("=" * 60)
    print("  JOB-AGENT TEST RUNNER")
    print("=" * 60)

    total_passed = total_failed = 0
    for name, module in suites:
        p, f = run_suite(name, module, verbose=args.verbose)
        total_passed += p
        total_failed += f

    print(f"\n{'='*60}")
    if total_failed == 0:
        print(f"  ✅  ALL {total_passed} TESTS PASSED")
    else:
        print(f"  ❌  {total_failed} FAILED, {total_passed} passed")
    print("=" * 60)

    sys.exit(1 if total_failed else 0)


if __name__ == "__main__":
    main()
