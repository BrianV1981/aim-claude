#!/usr/bin/env python3
"""
The Panopticon Protocol — unified deep search across all knowledge layers.
Searches continuity files, git history, and (when available) the Engram DB
with source attribution on every result.
"""
import os
import subprocess


def search_continuity(query, aim_root):
    """Search continuity/ markdown files for matching content."""
    if not query:
        return []
    cont_dir = os.path.join(aim_root, "continuity")
    if not os.path.isdir(cont_dir):
        return []

    results = []
    query_lower = query.lower()
    for filename in os.listdir(cont_dir):
        if not filename.endswith(".md"):
            continue
        filepath = os.path.join(cont_dir, filename)
        try:
            with open(filepath, "r") as f:
                content = f.read()
            if query_lower in content.lower():
                results.append({
                    "content": content[:500],
                    "source": f"continuity/{filename}",
                })
        except Exception:
            continue
    return results


def search_git_log(query, aim_root, limit=20):
    """Search git commit log for matching messages."""
    if not query:
        return []
    try:
        result = subprocess.run(
            ["git", "log", f"--grep={query}", "--oneline", f"-{limit}"],
            capture_output=True, text=True, cwd=aim_root, timeout=10,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return []
        results = []
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                results.append({"content": line.strip(), "source": "git_log"})
        return results
    except Exception:
        return []


def unified_recall(query, aim_root):
    """Unified search across all knowledge sources with attribution."""
    if not query:
        return []

    results = []
    results.extend(search_continuity(query, aim_root))
    results.extend(search_git_log(query, aim_root))
    return results
