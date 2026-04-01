"""
Unit tests for:
  - src/config_utils.py  (_merge_defaults, find_aim_root, load_config)
  - src/memory_utils.py  (should_run_tier, mark_tier_run, cleanup_consumed_files, commit_proposal)
  - src/datajack_plugin.py (NullKnowledgeProvider, load_knowledge_provider)
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock

# Load modules directly from file path to bypass any sys.modules stubs set by
# other test files (e.g. test_mcp_server.py permanently stubs "config_utils").
import importlib.util

SRC_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "src"))
if SRC_DIR not in sys.path:
    sys.path.insert(0, SRC_DIR)


def _load_src(name):
    path = os.path.join(SRC_DIR, f"{name}.py")
    spec = importlib.util.spec_from_file_location(f"_real_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


config_utils = _load_src("config_utils")
memory_utils = _load_src("memory_utils")
import datajack_plugin


# ─────────────────────────────────────────────────────────────────────────────
# config_utils — _merge_defaults
# ─────────────────────────────────────────────────────────────────────────────

class TestMergeDefaults(unittest.TestCase):
    def test_adds_missing_top_level_key(self):
        target = {"a": 1}
        defaults = {"a": 99, "b": 2}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["b"], 2)

    def test_does_not_overwrite_existing_key(self):
        target = {"a": 1}
        defaults = {"a": 99}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["a"], 1)

    def test_recursive_merge_nested_dict(self):
        target = {"paths": {"aim_root": "/real"}}
        defaults = {"paths": {"aim_root": "/default", "src_dir": "/default/src"}}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["paths"]["aim_root"], "/real")
        self.assertEqual(target["paths"]["src_dir"], "/default/src")

    def test_returns_changed_true_when_key_added(self):
        target = {}
        defaults = {"new_key": "val"}
        changed = config_utils._merge_defaults(target, defaults)
        self.assertTrue(changed)

    def test_returns_changed_false_when_no_change(self):
        target = {"a": 1}
        defaults = {"a": 99}
        changed = config_utils._merge_defaults(target, defaults)
        self.assertFalse(changed)

    def test_deep_nesting_three_levels(self):
        target = {"models": {"tiers": {"default": {"provider": "google"}}}}
        defaults = {"models": {"tiers": {"default": {"model": "flash"}, "new_tier": {}}}}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["models"]["tiers"]["default"]["provider"], "google")
        self.assertEqual(target["models"]["tiers"]["default"]["model"], "flash")
        self.assertIn("new_tier", target["models"]["tiers"])

    def test_non_dict_default_not_merged_into_existing(self):
        target = {"key": [1, 2, 3]}
        defaults = {"key": [4, 5, 6]}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["key"], [1, 2, 3])

    def test_empty_target_gets_all_defaults(self):
        target = {}
        defaults = {"a": 1, "b": {"c": 2}}
        config_utils._merge_defaults(target, defaults)
        self.assertEqual(target["a"], 1)
        self.assertEqual(target["b"]["c"], 2)


# ─────────────────────────────────────────────────────────────────────────────
# config_utils — find_aim_root
# ─────────────────────────────────────────────────────────────────────────────

class TestFindAimRoot(unittest.TestCase):
    def test_finds_root_when_config_json_exists(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core_dir = os.path.join(tmpdir, "core")
            os.makedirs(core_dir)
            with open(os.path.join(core_dir, "CONFIG.json"), "w") as f:
                json.dump({}, f)
            with patch("os.getcwd", return_value=tmpdir):
                root = config_utils.find_aim_root()
            self.assertEqual(root, tmpdir)

    def test_fallback_is_parent_of_src(self):
        # When no CONFIG.json is found via CWD walk, fallback is parent of __file__
        with patch("os.getcwd", return_value="/tmp"):
            root = config_utils.find_aim_root()
        # Should fall back to parent-of-parent of config_utils.py (the src/ file)
        expected = os.path.dirname(os.path.dirname(os.path.abspath(config_utils.__file__)))
        self.assertEqual(root, expected)

    def test_searches_parent_directories(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            core_dir = os.path.join(tmpdir, "core")
            os.makedirs(core_dir)
            with open(os.path.join(core_dir, "CONFIG.json"), "w") as f:
                json.dump({}, f)
            subdir = os.path.join(tmpdir, "sub", "deep")
            os.makedirs(subdir)
            with patch("os.getcwd", return_value=subdir):
                root = config_utils.find_aim_root()
            self.assertEqual(root, tmpdir)


# ─────────────────────────────────────────────────────────────────────────────
# config_utils — load_config
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadConfig(unittest.TestCase):
    def test_returns_default_config_when_file_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_path = os.path.join(tmpdir, "CONFIG.json")
            with patch.object(config_utils, "CONFIG_PATH", fake_path), \
                 patch.object(config_utils, "AIM_ROOT", tmpdir):
                cfg = config_utils.load_config()
        self.assertIn("paths", cfg)
        self.assertIn("models", cfg)
        self.assertIn("settings", cfg)

    def test_loads_existing_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "CONFIG.json")
            data = {"paths": {"aim_root": tmpdir}, "models": {}, "settings": {}}
            with open(cfg_path, "w") as f:
                json.dump(data, f)
            with patch.object(config_utils, "CONFIG_PATH", cfg_path), \
                 patch.object(config_utils, "AIM_ROOT", tmpdir):
                cfg = config_utils.load_config()
        self.assertEqual(cfg["paths"]["aim_root"], tmpdir)

    def test_merges_missing_defaults_into_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "CONFIG.json")
            # Write minimal config without 'settings'
            data = {"paths": {"aim_root": tmpdir}, "models": {}}
            with open(cfg_path, "w") as f:
                json.dump(data, f)
            with patch.object(config_utils, "CONFIG_PATH", cfg_path), \
                 patch.object(config_utils, "AIM_ROOT", tmpdir):
                cfg = config_utils.load_config()
        # 'settings' should have been merged in from defaults
        self.assertIn("settings", cfg)

    def test_returns_default_on_corrupt_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = os.path.join(tmpdir, "CONFIG.json")
            with open(cfg_path, "w") as f:
                f.write("not-json{{{")
            with patch.object(config_utils, "CONFIG_PATH", cfg_path), \
                 patch.object(config_utils, "AIM_ROOT", tmpdir):
                cfg = config_utils.load_config()
        self.assertIn("paths", cfg)


# ─────────────────────────────────────────────────────────────────────────────
# memory_utils — should_run_tier
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldRunTier(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "scrivener_state.json")

    def _patch(self):
        return patch.object(memory_utils, "STATE_FILE", self.state_path)

    def test_returns_true_when_no_state_file(self):
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertTrue(result)

    def test_returns_true_when_tier_not_in_state(self):
        with open(self.state_path, "w") as f:
            json.dump({"tiers": {}}, f)
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertTrue(result)

    def test_returns_false_when_interval_not_passed(self):
        recent = (datetime.now() - timedelta(hours=1)).isoformat()
        state = {"tiers": {"Tier2": {"last_run": recent}}}
        with open(self.state_path, "w") as f:
            json.dump(state, f)
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertFalse(result)

    def test_returns_true_when_interval_has_passed(self):
        old = (datetime.now() - timedelta(hours=25)).isoformat()
        state = {"tiers": {"Tier2": {"last_run": old}}}
        with open(self.state_path, "w") as f:
            json.dump(state, f)
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertTrue(result)

    def test_returns_true_on_corrupt_state_file(self):
        with open(self.state_path, "w") as f:
            f.write("{{bad json")
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertTrue(result)

    def test_exact_interval_boundary_returns_true(self):
        # Exactly at the interval boundary — should run
        exact = (datetime.now() - timedelta(hours=12)).isoformat()
        state = {"tiers": {"Tier2": {"last_run": exact}}}
        with open(self.state_path, "w") as f:
            json.dump(state, f)
        with self._patch():
            result = memory_utils.should_run_tier("Tier2", 12)
        self.assertTrue(result)


# ─────────────────────────────────────────────────────────────────────────────
# memory_utils — mark_tier_run
# ─────────────────────────────────────────────────────────────────────────────

class TestMarkTierRun(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = os.path.join(self.tmpdir, "scrivener_state.json")

    def _patch(self):
        return patch.object(memory_utils, "STATE_FILE", self.state_path)

    def test_creates_state_file_if_missing(self):
        with self._patch():
            memory_utils.mark_tier_run("Tier2")
        self.assertTrue(os.path.exists(self.state_path))

    def test_writes_timestamp_for_tier(self):
        with self._patch():
            memory_utils.mark_tier_run("Tier2")
        with open(self.state_path) as f:
            state = json.load(f)
        self.assertIn("Tier2", state["tiers"])
        self.assertIn("last_run", state["tiers"]["Tier2"])

    def test_updates_existing_tier_timestamp(self):
        old_ts = (datetime.now() - timedelta(hours=24)).isoformat()
        with open(self.state_path, "w") as f:
            json.dump({"tiers": {"Tier2": {"last_run": old_ts}}}, f)
        with self._patch():
            memory_utils.mark_tier_run("Tier2")
        with open(self.state_path) as f:
            state = json.load(f)
        new_ts = state["tiers"]["Tier2"]["last_run"]
        self.assertNotEqual(new_ts, old_ts)

    def test_preserves_other_tiers(self):
        with open(self.state_path, "w") as f:
            json.dump({"tiers": {"Tier3": {"last_run": "2026-01-01"}}}, f)
        with self._patch():
            memory_utils.mark_tier_run("Tier2")
        with open(self.state_path) as f:
            state = json.load(f)
        self.assertIn("Tier3", state["tiers"])
        self.assertIn("Tier2", state["tiers"])


# ─────────────────────────────────────────────────────────────────────────────
# memory_utils — cleanup_consumed_files
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanupConsumedFiles(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.archive_dir = os.path.join(self.tmpdir, "memory", "archive")

    def _patch_root(self):
        return patch.object(memory_utils, "AIM_ROOT", self.tmpdir)

    def _create_file(self, name, content="test"):
        path = os.path.join(self.tmpdir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_archives_file_by_default(self):
        src = self._create_file("PROPOSAL_001.md")
        with self._patch_root():
            memory_utils.cleanup_consumed_files([src])
        self.assertFalse(os.path.exists(src))
        archived = os.path.join(self.archive_dir, "PROPOSAL_001.md")
        self.assertTrue(os.path.exists(archived))

    def test_deletes_file_in_delete_mode(self):
        src = self._create_file("old.md")
        with self._patch_root():
            memory_utils.cleanup_consumed_files([src], cleanup_mode="delete")
        # File should be deleted
        self.assertFalse(os.path.exists(src))
        # Archive dir is created as a side effect but file is NOT archived
        if os.path.exists(self.archive_dir):
            self.assertNotIn("old.md", os.listdir(self.archive_dir))

    def test_handles_collision_with_timestamp_suffix(self):
        src1 = self._create_file("PROPOSAL_001.md", "first")
        src2 = self._create_file("PROPOSAL_002.md", "second")
        # Pre-create the destination to force collision on src2
        os.makedirs(self.archive_dir, exist_ok=True)
        with open(os.path.join(self.archive_dir, "PROPOSAL_002.md"), "w") as f:
            f.write("existing")
        with self._patch_root():
            memory_utils.cleanup_consumed_files([src1, src2])
        # src1 archived normally
        self.assertTrue(os.path.exists(os.path.join(self.archive_dir, "PROPOSAL_001.md")))
        # src2 archived with timestamp suffix — check count increased
        archived_files = os.listdir(self.archive_dir)
        proposal_files = [f for f in archived_files if "PROPOSAL_002" in f]
        self.assertEqual(len(proposal_files), 2)

    def test_skips_nonexistent_files_gracefully(self):
        with self._patch_root():
            memory_utils.cleanup_consumed_files(["/no/such/file.md"])
        # No crash, no archive dir necessarily created

    def test_empty_list_is_noop(self):
        with self._patch_root():
            memory_utils.cleanup_consumed_files([])
        self.assertFalse(os.path.exists(self.archive_dir))


# ─────────────────────────────────────────────────────────────────────────────
# memory_utils — commit_proposal
# ─────────────────────────────────────────────────────────────────────────────

class TestCommitProposal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.proposal_dir = os.path.join(self.tmpdir, "memory", "proposals")
        self.memory_path = os.path.join(self.tmpdir, "core", "MEMORY.md")
        os.makedirs(self.proposal_dir)
        os.makedirs(os.path.dirname(self.memory_path))

    def _write_proposal(self, name, content):
        path = os.path.join(self.proposal_dir, name)
        with open(path, "w") as f:
            f.write(content)
        return path

    def test_returns_false_when_no_proposal_dir(self):
        result = memory_utils.commit_proposal(os.path.join(self.tmpdir, "empty"))
        self.assertFalse(result)

    def test_returns_false_when_no_proposals(self):
        result = memory_utils.commit_proposal(self.tmpdir)
        self.assertFalse(result)

    def test_extracts_memory_delta_section(self):
        content = "# Proposal\n\n### 3. MEMORY DELTA\nNew memory content here.\n"
        self._write_proposal("PROPOSAL_2026-03-31.md", content)
        result = memory_utils.commit_proposal(self.tmpdir)
        self.assertTrue(result)
        with open(self.memory_path) as f:
            mem = f.read()
        self.assertIn("New memory content here.", mem)
        self.assertNotIn("### 3. MEMORY DELTA", mem)

    def test_uses_whole_content_when_no_delta_section(self):
        content = "Just raw memory content\nno delta marker"
        self._write_proposal("PROPOSAL_2026-03-31.md", content)
        memory_utils.commit_proposal(self.tmpdir)
        with open(self.memory_path) as f:
            mem = f.read()
        self.assertIn("Just raw memory content", mem)

    def test_strips_markdown_fences_from_delta(self):
        content = "### 3. MEMORY DELTA\n```markdown\n# Clean Content\n```\n"
        self._write_proposal("PROPOSAL_2026-03-31.md", content)
        memory_utils.commit_proposal(self.tmpdir)
        with open(self.memory_path) as f:
            mem = f.read()
        self.assertNotIn("```", mem)
        self.assertIn("# Clean Content", mem)

    def test_uses_latest_proposal_alphabetically(self):
        self._write_proposal("PROPOSAL_2026-03-29.md", "### 3. MEMORY DELTA\nOLD")
        self._write_proposal("PROPOSAL_2026-03-31.md", "### 3. MEMORY DELTA\nNEW")
        memory_utils.commit_proposal(self.tmpdir)
        with open(self.memory_path) as f:
            mem = f.read()
        self.assertIn("NEW", mem)
        self.assertNotIn("OLD", mem)

    def test_archives_committed_proposal(self):
        self._write_proposal("PROPOSAL_2026-03-31.md", "### 3. MEMORY DELTA\ndata")
        memory_utils.commit_proposal(self.tmpdir)
        # Original proposal should be moved to archive
        self.assertFalse(
            os.path.exists(os.path.join(self.proposal_dir, "PROPOSAL_2026-03-31.md"))
        )
        self.assertTrue(
            os.path.exists(os.path.join(self.tmpdir, "memory", "archive", "PROPOSAL_2026-03-31.md"))
        )


# ─────────────────────────────────────────────────────────────────────────────
# datajack_plugin — NullKnowledgeProvider
# ─────────────────────────────────────────────────────────────────────────────

class TestNullKnowledgeProvider(unittest.TestCase):
    def setUp(self):
        self.provider = datajack_plugin.NullKnowledgeProvider("test error")

    def test_get_knowledge_map_returns_error_dict(self):
        result = self.provider.get_knowledge_map()
        self.assertIn("error", result)
        self.assertEqual(result["error"], "test error")

    def test_semantic_search_returns_list_with_error_entry(self):
        result = self.provider.semantic_search("query")
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["score"], 0.0)
        self.assertIn("SYSTEM OFFLINE", result[0]["content"])

    def test_lexical_search_returns_empty_list(self):
        result = self.provider.lexical_search("query")
        self.assertEqual(result, [])

    def test_close_runs_without_error(self):
        self.provider.close()  # Should not raise

    def test_default_error_message(self):
        p = datajack_plugin.NullKnowledgeProvider()
        result = p.get_knowledge_map()
        self.assertIn("error", result)

    def test_custom_top_k_ignored_gracefully(self):
        result = self.provider.semantic_search("q", top_k=20)
        self.assertIsInstance(result, list)


# ─────────────────────────────────────────────────────────────────────────────
# datajack_plugin — load_knowledge_provider
# ─────────────────────────────────────────────────────────────────────────────

class TestLoadKnowledgeProvider(unittest.TestCase):
    def test_returns_null_provider_when_forensicdb_unavailable(self):
        import types
        broken_stub = types.ModuleType("plugins.datajack.forensic_utils")
        broken_stub.ForensicDB = MagicMock(side_effect=ImportError("no keyring"))
        with patch.dict(sys.modules, {"plugins.datajack.forensic_utils": broken_stub}):
            provider = datajack_plugin.load_knowledge_provider()
        self.assertIsInstance(provider, datajack_plugin.NullKnowledgeProvider)

    def test_returns_forensicdb_instance_when_available(self):
        mock_db = MagicMock()
        import types
        good_stub = types.ModuleType("plugins.datajack.forensic_utils")
        good_stub.ForensicDB = MagicMock(return_value=mock_db)
        with patch.dict(sys.modules, {"plugins.datajack.forensic_utils": good_stub}):
            provider = datajack_plugin.load_knowledge_provider()
        self.assertEqual(provider, mock_db)

    def test_null_provider_on_any_exception(self):
        import types
        broken_stub = types.ModuleType("plugins.datajack.forensic_utils")
        broken_stub.ForensicDB = MagicMock(side_effect=RuntimeError("db crash"))
        with patch.dict(sys.modules, {"plugins.datajack.forensic_utils": broken_stub}):
            provider = datajack_plugin.load_knowledge_provider()
        self.assertIsInstance(provider, datajack_plugin.NullKnowledgeProvider)


if __name__ == "__main__":
    unittest.main()
