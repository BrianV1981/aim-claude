#!/usr/bin/env python3
"""
Freshness tracker for self-upgrading engrams.
Detects when source documentation has changed since a cartridge was baked,
enabling differential re-indexing.
"""
import hashlib
import os

# File extensions that are valid for engram ingestion
TEXT_EXTENSIONS = {'.md', '.markdown', '.txt', '.py', '.rs', '.js', '.ts', '.rst'}


def hash_source_files(directory):
    """Returns a dict of {relative_path: sha256_hex} for all text files in directory."""
    if not os.path.isdir(directory):
        return {}
    result = {}
    for root, _, files in os.walk(directory):
        for filename in files:
            ext = os.path.splitext(filename)[1].lower()
            if ext not in TEXT_EXTENSIONS:
                continue
            full_path = os.path.join(root, filename)
            rel_path = os.path.relpath(full_path, directory)
            with open(full_path, "rb") as f:
                file_hash = hashlib.sha256(f.read()).hexdigest()
            result[rel_path] = file_hash
    return result


def detect_stale_files(stored_hashes, directory):
    """Compare stored hashes against current files to find changes.

    Returns dict with keys: modified, added, deleted (each a list of relative paths).
    """
    current_hashes = hash_source_files(directory)
    modified = []
    added = []
    deleted = []

    for path, current_hash in current_hashes.items():
        if path not in stored_hashes:
            added.append(path)
        elif stored_hashes[path] != current_hash:
            modified.append(path)

    for path in stored_hashes:
        if path not in current_hashes:
            deleted.append(path)

    return {"modified": modified, "added": added, "deleted": deleted}
