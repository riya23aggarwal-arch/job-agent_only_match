"""
Riya Aggarwal — Candidate Profile
Source of truth for scoring engine, resume tailoring, and cover letter generation.
Updated to match final resume (March 2026).
"""

CANDIDATE_PROFILE = {
    "name": "Riya Aggarwal",
    "email": "riya23aggarwal@gmail.com",
    "phone": "+1 (831) 869-4225",
    "location": "San Jose, CA",
    "linkedin": "linkedin.com/in/ragrwl",
    "years_experience": 7,

    # ── SKILLS BY WEIGHT ──────────────────────────────────────────────────────
    # High = core skills from resume, heavily weighted in scoring

    "skills_high": [
        "C",
        "Linux internals",
        "device drivers",
        "BSP",
        "hardware bring-up",
        "platform initialization",
        "kernel debugging",
        "networking",
        "optics",
        "firmware",
        "multithreading",
        "memory management",
        "IPC",
        "packet forwarding",
        "ethernet",
    ],

    "skills_medium": [
        "Python",
        "automation",
        "debugging",
        "shell scripting",
        "PyATS",
        "pytest",
        "regression testing",
        "system validation",
        "GDB",
        "ADB",
        "log analysis",
        "CI/CD",
        "failure triage",
        "boot diagnostics",
        "runtime diagnostics",
    ],

    "skills_low": [
        "SPI",
        "I2C",
        "GPIO",
        "UART",
        "QSFP",
        "SFP",
        "gRPC",
        "NETCONF",
        "YANG",
        "git",
        "embedded systems",
        "cross-compilation",
        "TCP/IP",
    ],

    # ── ANTI-SKILLS — penalize irrelevant role types ──────────────────────────
    "anti_skills": [
        "React",
        "Angular",
        "Vue",
        "frontend",
        "UI engineer",
        "Java only",
        "Ruby",
        "Rails",
        "mobile development",
        "iOS",
        "Android",
        "data science",
        "machine learning",
        "ML engineer",
    ],

    # ── EXPERIENCE ────────────────────────────────────────────────────────────

    "experience": [
        {
            "company": "Cognizant (Google AR/VR)",
            "title": "Technical Solutions Engineer",
            "duration": "May 2025–Present",
            "highlights": [
                "Debug data upload failures across device-to-app-to-server pipeline for AR prototype devices — tracing issues across firmware, OS, and application layers using ADB, Linux logs, and debugging tools",
                "Develop Python and shell utilities to automate device setup, reproduce upload failure scenarios, and validate data integrity across pipeline stages",
                "Work directly with engineering teams to triage and resolve field-reported issues, ensuring collected user data reaches backend servers reliably",
            ],
            "tags": ["Linux", "firmware", "Python", "ADB", "debugging", "automation", "pipeline"],
        },
        {
            "company": "Cisco Systems",
            "title": "Software Engineer II",
            "duration": "Jan 2022–Aug 2023",
            "highlights": [
                "FPD upgrade automation: Developed and shipped a Python-based FPD upgrade tool to customers across multiple NCS platforms including NCS1010 — enabling self-service firmware upgrades that previously required Cisco engineer involvement. Implemented serial upgrade sequencing with automated failure detection and rollback, preventing device bricking on upgrade failure",
                "Optics driver: Implemented optics driver support for a new NCS platform by extending shared C code rather than duplicating it — designed a CSV-driven feature flag system read at boot time to declare per-platform capabilities. Coordinated with multiple platform teams to avoid regressions, then built automated test coverage across all affected platforms",
                "Collaborated with platform, hardware, and validation teams to debug low-level Linux system issues spanning firmware, drivers, and hardware interactions",
            ],
            "tags": ["C", "Linux", "device drivers", "optics", "firmware", "platform", "networking",
                     "Python", "automation", "FPD", "NCS", "BSP"],
        },
        {
            "company": "Capgemini (Cisco NCS2K)",
            "title": "Software Engineer I",
            "duration": "Feb 2019–Jan 2022",
            "highlights": [
                "Platform automation suite: Built a Python + PyATS automation suite for comprehensive NCS2K platform validation — covering system bring-up, alarms, reloads, and traffic flows. Integrated into CI/CD pipeline to catch field issues before release, adopted as the standard regression framework",
                "IDLE insertion / link verification: Implemented IDLE insertion feature in C for Cisco NCS1004 — spoofed packets at the PCS layer to send IDLE frames for end-to-end Ethernet link verification without real traffic, eliminating dependency on external traffic generators and reducing testing cost by ~70%",
            ],
            "tags": ["networking", "PyATS", "automation", "Python", "Ethernet", "C",
                     "CI/CD", "regression", "NCS2K", "PCS layer"],
        },
    ],

    "education": [
        {"degree": "MS Computer Science", "school": "UC Santa Cruz"},
        {"degree": "BTech Computer Science", "school": "Mody University, India"},
    ],

    # ── TARGET ROLES ──────────────────────────────────────────────────────────

    "target_roles": [
        "Software Engineer",
        "Systems Engineer",
        "Embedded Engineer",
        "Platform Engineer",
        "Kernel Engineer",
        "Linux Engineer",
        "Firmware Engineer",
        "Driver Development Engineer",
        "Network Systems Engineer",
        "Infrastructure Engineer",
        "Software Developer",
        "Technical Solutions Engineer",
    ],

    "preferred_locations": [
        # Bay Area
        "San Jose", "San Francisco", "Santa Clara", "Sunnyvale",
        "Mountain View", "Palo Alto", "Menlo Park", "Fremont",
        "Cupertino", "Oakland", "Berkeley", "Milpitas",
        "Bay Area", "Silicon Valley",
        # Other US hubs
        "Seattle", "Bellevue", "Austin", "Boston", "New York",
        "Chicago", "Denver", "Atlanta", "Los Angeles", "San Diego",
        "Portland", "Phoenix", "Pittsburgh", "Raleigh", "Dallas",
        "Washington DC", "Arlington", "Bethesda",
        "RTP", "Research Triangle", "Durham",
        "Hillsboro", "Beaverton",
        # Remote
        "Remote", "US Remote", "Hybrid",
        # State signals
        ", CA", ", WA", ", TX", ", NY", ", MA",
    ],

    # ── RESUME BULLETS FOR TAILORING ─────────────────────────────────────────
    # Used by resume/tailor.py to select and reorder bullets per job focus

    "resume_bullets": {
        "networking": [
            "Implemented optics driver in C for NCS platforms with CSV-driven feature flags for cross-platform support",
            "Implemented IDLE insertion at PCS layer for Ethernet link verification on NCS1004, removing need for external traffic generators",
            "Built PyATS automation suite covering system bring-up, alarms, reloads, and traffic flows for NCS2K platform",
        ],
        "linux_kernel": [
            "Debug data upload pipeline failures on AR prototype devices across firmware, OS, and application layers using ADB and Linux debugging tools",
            "Debugged low-level Linux system issues spanning firmware, drivers, and hardware at Cisco Systems",
            "Implemented serial FPD upgrade sequencing with automated rollback to prevent device bricking on upgrade failure",
        ],
        "device_drivers": [
            "Implemented optics driver support for new NCS platform by extending shared C code with CSV-driven boot-time feature flags",
            "Coordinated with multiple platform teams to validate changes across all affected NCS SKUs without regressions",
            "Developed and shipped Python-based FPD upgrade tool with failure detection and rollback across multiple NCS platforms",
        ],
        "automation": [
            "Developed Python and shell utilities to automate device setup, reproduce failure scenarios, and validate data integrity on AR devices",
            "Built Python + PyATS automation suite integrated into CI/CD for NCS2K platform regression testing",
            "Built automated FPD upgrade tool shipped to customers for self-service firmware upgrades across NCS platforms",
        ],
        "embedded": [
            "Debug AR prototype device pipeline failures across firmware, OS, and application layers",
            "Implemented FPD upgrade automation with serial sequencing and rollback for embedded hardware safety",
            "Designed CSV-driven boot-time feature flag system for cross-platform optics driver on NCS hardware",
        ],
    },
}
