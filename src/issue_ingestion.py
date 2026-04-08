#!/usr/bin/env python3
"""
Forum & Issue Ingestion Pipeline.
Parses GitHub issues into engram-compatible fragments for RAG ingestion.
"""
import hashlib


def _content_hash(text):
    return hashlib.sha256(text.encode()).hexdigest()


def parse_github_issue(issue):
    """Parse a GitHub issue JSON into a list of engram-compatible fragments."""
    fragments = []
    number = issue.get("number", 0)
    title = issue.get("title", "")
    body = issue.get("body") or ""
    source = f"github#{ number}"

    # Main fragment: title + body
    main_content = f"[#{number}] {title}\n\n{body}".strip()
    fragments.append({
        "content": main_content,
        "type": "community_knowledge",
        "source": source,
        "content_hash": _content_hash(main_content),
    })

    # Comment fragments
    for comment in issue.get("comments", []):
        c_body = comment.get("body", "")
        if c_body.strip():
            fragments.append({
                "content": f"[#{number} comment] {c_body}",
                "type": "community_knowledge",
                "source": source,
                "content_hash": _content_hash(c_body),
            })

    return fragments


def deduplicate_against_existing(fragments, existing_hashes):
    """Remove fragments whose content_hash is already known."""
    return [f for f in fragments if f.get("content_hash") not in existing_hashes]
