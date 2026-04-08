#!/usr/bin/env python3
"""
Sovereignty Dashboard — agent health and status at a glance.
Shows engram DB stats, mail count, continuity status, and git activity.
"""
import os
import subprocess


def gather_dashboard_data(aim_root):
    """Collect system metrics for the dashboard."""
    data = {
        "engram_stats": {"databases": 0, "total_size_mb": 0},
        "mail_count": 0,
        "git_summary": "",
        "continuity_files": 0,
    }

    # Engram DB stats
    archive_dir = os.path.join(aim_root, "archive")
    if os.path.isdir(archive_dir):
        db_files = [f for f in os.listdir(archive_dir) if f.endswith(".db")]
        total_size = sum(
            os.path.getsize(os.path.join(archive_dir, f))
            for f in db_files if os.path.isfile(os.path.join(archive_dir, f))
        )
        data["engram_stats"] = {
            "databases": len(db_files),
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

    # Continuity files
    cont_dir = os.path.join(aim_root, "continuity")
    if os.path.isdir(cont_dir):
        md_files = [f for f in os.listdir(cont_dir) if f.endswith(".md") and f != "UNREAD_MAIL.md"]
        data["continuity_files"] = len(md_files)

        # Mail count
        mail_path = os.path.join(cont_dir, "UNREAD_MAIL.md")
        if os.path.exists(mail_path):
            with open(mail_path) as f:
                lines = f.readlines()
            data["mail_count"] = sum(1 for l in lines if l.strip().startswith("- "))

    # Git summary
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, cwd=aim_root, timeout=10,
        )
        data["git_summary"] = result.stdout.strip()
    except Exception:
        pass

    return data


def format_dashboard(data):
    """Render a terminal-friendly dashboard."""
    lines = [
        "╔══════════════════════════════════════════╗",
        "║     A.I.M. SOVEREIGNTY STATUS DASHBOARD  ║",
        "╚══════════════════════════════════════════╝",
        "",
        f"  Engram DBs:        {data['engram_stats']['databases']} ({data['engram_stats']['total_size_mb']} MB)",
        f"  Continuity Files:  {data['continuity_files']}",
        f"  Unread Mail:       {data['mail_count']}",
        "",
        "  Recent Git Activity:",
    ]
    if data.get("git_summary"):
        for line in data["git_summary"].split("\n")[:5]:
            lines.append(f"    {line}")
    else:
        lines.append("    (no recent activity)")

    return "\n".join(lines)
