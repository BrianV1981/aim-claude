#!/usr/bin/env python3
"""
Cartridge discovery and validation utilities for the DataJack system.
Lists, validates, and extracts metadata from .engram cartridge files.
"""
import os
import json
import zipfile
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_REQUIRED_FIELDS = ("name", "version", "embedding_model", "fragment_count", "created_at")


def list_cartridges(engram_dir):
    """Returns a list of absolute paths to .engram files in the given directory."""
    if not os.path.isdir(engram_dir):
        return []
    return sorted([
        os.path.join(engram_dir, f)
        for f in os.listdir(engram_dir)
        if f.endswith(".engram")
    ])


def validate_cartridge(cartridge_path):
    """Returns True if the cartridge is a valid zip containing metadata.json."""
    if not os.path.exists(cartridge_path):
        return False
    try:
        with zipfile.ZipFile(cartridge_path, "r") as zf:
            return "metadata.json" in zf.namelist()
    except (zipfile.BadZipFile, Exception):
        return False


def get_cartridge_info(cartridge_path):
    """Extracts and returns metadata dict from a cartridge. Returns None if invalid."""
    if not validate_cartridge(cartridge_path):
        return None
    try:
        with zipfile.ZipFile(cartridge_path, "r") as zf:
            meta = json.loads(zf.read("metadata.json"))
        if "name" not in meta:
            meta["name"] = Path(cartridge_path).stem
        return meta
    except Exception:
        return None


def generate_manifest(name, version, embedding_model, fragment_count, source_repo=None):
    """Creates a manifest dict with required cartridge metadata."""
    manifest = {
        "name": name,
        "version": version,
        "embedding_model": embedding_model,
        "fragment_count": fragment_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if source_repo:
        manifest["source_repo"] = source_repo
    return manifest


def validate_manifest(manifest):
    """Returns True if the manifest dict contains all required fields."""
    if not isinstance(manifest, dict):
        return False
    return all(field in manifest for field in MANIFEST_REQUIRED_FIELDS)
