"""
Tests for the Single-Shot Memory Compiler (hooks/session_summarizer.py).

Validates the core compiler logic WITHOUT calling an actual LLM.
Tests cover: extract_file_content, atomic_write, process_transcript (mocked LLM),
main() argument parsing, and cognitive mode gating.
"""
import importlib.util
import json
import os
import sys
import tempfile
import types
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

AIM_CLAUDE_ROOT = str(Path(__file__).parent.parent.parent)


# ---------------------------------------------------------------------------
# Stubs
# ---------------------------------------------------------------------------

def _ensure_stub(name, **attrs):
    if name not in sys.modules:
        mod = types.ModuleType(name)
        for k, v in attrs.items():
            setattr(mod, k, v)
        sys.modules[name] = mod
    return sys.modules[name]

_ensure_stub("keyring", get_password=lambda *a, **k: None, set_password=lambda *a, **k: None)
_ensure_stub("google")
_ensure_stub("google.genai")


def _load_compiler(cwd_override=None, config_override=None):
    """Load session_summarizer.py with mocked cwd and config."""
    mod_name = "_test_compiler"
    sys.modules.pop(mod_name, None)

    spec = importlib.util.spec_from_file_location(
        mod_name,
        os.path.join(AIM_CLAUDE_ROOT, "hooks", "session_summarizer.py"),
    )
    mod = importlib.util.module_from_spec(spec)

    with patch("os.getcwd", return_value=cwd_override or AIM_CLAUDE_ROOT):
        spec.loader.exec_module(mod)

    if config_override is not None:
        mod.CONFIG = config_override

    return mod


# ===========================================================================
# extract_file_content
# ===========================================================================

class TestExtractFileContent:

    def test_extracts_memory_block(self):
        mod = _load_compiler()
        text = """Some preamble.

### core/MEMORY.md
```markdown
# Memory
- fact one
- fact two
```

### CLAUDE.md
```markdown
# Rules
- rule one
```
"""
        result = mod.extract_file_content(text, "core/MEMORY.md")
        assert result is not None
        assert "fact one" in result
        assert "fact two" in result

    def test_extracts_claude_block(self):
        mod = _load_compiler()
        text = """### core/MEMORY.md
```markdown
# Memory
```

### CLAUDE.md
```markdown
# Rules
- rule one
```
"""
        result = mod.extract_file_content(text, "CLAUDE.md")
        assert result is not None
        assert "rule one" in result

    def test_returns_none_on_missing_block(self):
        mod = _load_compiler()
        result = mod.extract_file_content("no blocks here", "core/MEMORY.md")
        assert result is None


# ===========================================================================
# atomic_write
# ===========================================================================

class TestAtomicWrite:

    def test_writes_file(self):
        mod = _load_compiler()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            path = f.name
        try:
            mod.atomic_write(path, "hello world")
            with open(path, 'r') as f:
                assert f.read() == "hello world\n"
        finally:
            os.unlink(path)

    def test_overwrites_existing(self):
        mod = _load_compiler()
        with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
            f.write("old content")
            path = f.name
        try:
            mod.atomic_write(path, "new content")
            with open(path, 'r') as f:
                assert f.read() == "new content\n"
        finally:
            os.unlink(path)


# ===========================================================================
# process_transcript (mocked LLM)
# ===========================================================================

class TestProcessTranscript:

    def _setup_temp_env(self, tmp_path):
        """Create a minimal aim-like directory with CONFIG.json, MEMORY.md, CLAUDE.md."""
        core = tmp_path / "core"
        core.mkdir()
        config = {"settings": {"cognitive_mode": "monolithic"}, "models": {"tier1": "test"}}
        (core / "CONFIG.json").write_text(json.dumps(config))
        (core / "MEMORY.md").write_text("# Memory\n- old fact\n")
        (tmp_path / "CLAUDE.md").write_text("# Rules\n- old rule\n")
        transcript = tmp_path / "transcript.md"
        transcript.write_text("# Session\nUSER: did stuff\nA.I.M.: confirmed\n")
        return str(transcript)

    def test_process_transcript_updates_files(self, tmp_path):
        md_path = self._setup_temp_env(tmp_path)
        mod = _load_compiler(cwd_override=str(tmp_path))

        # Override paths to point at tmp_path
        mod.MEMORY_PATH = str(tmp_path / "core" / "MEMORY.md")
        mod.CLAUDE_PATH = str(tmp_path / "CLAUDE.md")

        fake_output = """### core/MEMORY.md
```markdown
# Memory
- old fact
- new architectural decision (Added: 2026-04-08)
```

### CLAUDE.md
```markdown
# Rules
- old rule
- new safety constraint (Added: 2026-04-08)
```
"""
        mod.generate_reasoning = MagicMock(return_value=fake_output)

        result = mod.process_transcript(md_path)
        assert result is True

        with open(mod.MEMORY_PATH, 'r') as f:
            mem = f.read()
        assert "new architectural decision" in mem

        with open(mod.CLAUDE_PATH, 'r') as f:
            claude = f.read()
        assert "new safety constraint" in claude

    def test_process_transcript_fails_on_bad_llm_output(self, tmp_path):
        md_path = self._setup_temp_env(tmp_path)
        mod = _load_compiler(cwd_override=str(tmp_path))
        mod.MEMORY_PATH = str(tmp_path / "core" / "MEMORY.md")
        mod.CLAUDE_PATH = str(tmp_path / "CLAUDE.md")

        mod.generate_reasoning = MagicMock(return_value="Error: API timeout")
        result = mod.process_transcript(md_path)
        assert result is False

    def test_process_transcript_fails_on_no_blocks(self, tmp_path):
        md_path = self._setup_temp_env(tmp_path)
        mod = _load_compiler(cwd_override=str(tmp_path))
        mod.MEMORY_PATH = str(tmp_path / "core" / "MEMORY.md")
        mod.CLAUDE_PATH = str(tmp_path / "CLAUDE.md")

        mod.generate_reasoning = MagicMock(return_value="I updated the files.")
        result = mod.process_transcript(md_path)
        assert result is False

    def test_process_transcript_fails_without_reasoning(self, tmp_path):
        md_path = self._setup_temp_env(tmp_path)
        mod = _load_compiler(cwd_override=str(tmp_path))
        mod.generate_reasoning = None
        result = mod.process_transcript(md_path)
        assert result is False


# ===========================================================================
# main() argument parsing and gating
# ===========================================================================

class TestMain:

    def test_light_mode_skips(self, capsys):
        mod = _load_compiler()
        mod.main(["--light"])
        out = capsys.readouterr().out
        assert "light_mode_active" in out

    def test_frontline_mode_skips(self, capsys):
        mod = _load_compiler(config_override={
            "settings": {"cognitive_mode": "frontline"},
        })
        mod.main([])
        out = capsys.readouterr().out
        assert "frontline_mode_offloads_compute" in out

    def test_no_transcript_skips(self, tmp_path, capsys):
        mod = _load_compiler(config_override={
            "settings": {"cognitive_mode": "monolithic"},
        })
        # Point archive/history at an empty dir so no fallback transcript is found
        mod.AIM_ROOT = str(tmp_path)
        mod.main([])
        out = capsys.readouterr().out
        assert "no_transcript_found" in out

    def test_direct_md_path(self, tmp_path, capsys):
        transcript = tmp_path / "test.md"
        transcript.write_text("# test session")
        mod = _load_compiler(config_override={
            "settings": {"cognitive_mode": "monolithic"},
        })
        mod.generate_reasoning = MagicMock(return_value="Error: test")
        mod.MEMORY_PATH = str(tmp_path / "MEMORY.md")
        mod.CLAUDE_PATH = str(tmp_path / "CLAUDE.md")

        mod.main([str(transcript)])
        out = capsys.readouterr().out
        assert '"updated": 0' in out
