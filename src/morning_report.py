#!/usr/bin/env python3
"""
Strategic Synthesis & Morning Report generator.
Aggregates project state (git activity, unread mail, open issues)
into a structured briefing for the operator.
"""
import os
import subprocess
from datetime import datetime, timezone


def gather_report_data(aim_root):
    """Aggregate project state into a structured dict."""
    data = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "git_log": "",
        "unread_mail": "",
        "open_issues": "",
    }

    # Git log (last 10 commits)
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, cwd=aim_root, timeout=10,
        )
        data["git_log"] = result.stdout.strip()
    except Exception:
        pass

    # Unread swarm mail
    mail_path = os.path.join(aim_root, "continuity", "UNREAD_MAIL.md")
    if os.path.exists(mail_path):
        with open(mail_path, "r") as f:
            data["unread_mail"] = f.read().strip()

    # Open issues (try gh CLI)
    try:
        result = subprocess.run(
            ["gh", "issue", "list", "--state", "open", "--limit", "20", "--json", "number,title"],
            capture_output=True, text=True, cwd=aim_root, timeout=15,
        )
        if result.returncode == 0:
            data["open_issues"] = result.stdout.strip()
    except Exception:
        pass

    return data


def format_report(data):
    """Render a human-readable markdown morning report."""
    lines = [
        f"# A.I.M. Strategic Briefing — Morning Report",
        f"**Generated:** {data.get('timestamp', 'Unknown')}",
        "",
    ]

    # Git Activity
    lines.append("## Recent Git Activity")
    if data.get("git_log"):
        lines.append("```")
        lines.append(data["git_log"])
        lines.append("```")
    else:
        lines.append("_No recent git activity._")
    lines.append("")

    # Unread Mail
    lines.append("## Swarm Mail")
    if data.get("unread_mail"):
        lines.append(data["unread_mail"])
    else:
        lines.append("_No unread mail._")
    lines.append("")

    # Open Issues
    lines.append("## Open Issues")
    if data.get("open_issues"):
        lines.append(data["open_issues"])
    else:
        lines.append("_Could not retrieve open issues._")

    return "\n".join(lines)
