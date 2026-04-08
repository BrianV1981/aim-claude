#!/usr/bin/env python3
"""
Cartridge discovery and validation utilities for the DataJack system.
Lists, validates, and extracts metadata from .engram cartridge files.
"""
import os
import json
import zipfile
from pathlib import Path


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
