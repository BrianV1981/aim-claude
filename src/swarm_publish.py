#!/usr/bin/env python3
"""
Sovereign Swarm 2.0 — cartridge publishing protocol.
Publishes .engram cartridges to a registry for swarm discovery.
"""
import importlib.util
import os
import shutil
import sys


def _import_cartridge_utils():
    """Import cartridge_utils without relying on package path (avoids test stub conflicts)."""
    utils_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "plugins", "datajack", "cartridge_utils.py"
    )
    if not os.path.exists(utils_path):
        # Fallback: try relative to this file's directory
        utils_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "plugins", "datajack", "cartridge_utils.py"
        )
    spec = importlib.util.spec_from_file_location("_cartridge_utils", utils_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_cart_utils = _import_cartridge_utils()
validate_cartridge = _cart_utils.validate_cartridge
get_cartridge_info = _cart_utils.get_cartridge_info


def publish_cartridge(cartridge_path, registry_dir):
    """Publish a .engram cartridge to the swarm registry."""
    if not validate_cartridge(cartridge_path):
        return {"success": False, "error": "Invalid cartridge — failed validation"}

    os.makedirs(registry_dir, exist_ok=True)
    dest = os.path.join(registry_dir, os.path.basename(cartridge_path))
    shutil.copy2(cartridge_path, dest)
    return {"success": True, "path": dest}


def list_published(registry_dir):
    """List all published cartridges in the registry with their metadata."""
    if not os.path.isdir(registry_dir):
        return []
    results = []
    for f in sorted(os.listdir(registry_dir)):
        if not f.endswith(".engram"):
            continue
        info = get_cartridge_info(os.path.join(registry_dir, f))
        if info:
            results.append(info)
    return results
