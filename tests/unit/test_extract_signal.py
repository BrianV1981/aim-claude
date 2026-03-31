"""
Unit tests for scripts/extract_signal.py

Tests cover:
- find_session_files(): discovery with and without explicit path
- extract_signal(): JSONL parsing, role filtering, content extraction,
  tool_use action capture, thinking block truncation, error handling
- skeleton_to_markdown(): markdown formatting, role headers, thoughts,
  actions, empty input handling
- CLI compression ratio: signal output is smaller than raw input
"""

import json
import os
import sys
import tempfile
import unittest

# Make extract_signal importable directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "scripts"))
from extract_signal import extract_signal, find_session_files, skeleton_to_markdown


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_jsonl(path, messages):
    with open(path, "w") as f:
        for msg in messages:
            f.write(json.dumps(msg) + "\n")


def _user_msg(text, timestamp="2026-03-31T00:00:00Z", session_id="test-session"):
    return {
        "type": "user",
        "timestamp": timestamp,
        "sessionId": session_id,
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": text}],
        },
    }


def _assistant_msg(text=None, thoughts=None, tools=None,
                   timestamp="2026-03-31T00:01:00Z", session_id="test-session"):
    content = []
    if text:
        content.append({"type": "text", "text": text})
    for thought in (thoughts or []):
        content.append({"type": "thinking", "thinking": thought})
    for tool in (tools or []):
        content.append({
            "type": "tool_use",
            "name": tool["name"],
            "input": tool.get("input", {}),
        })
    return {
        "type": "assistant",
        "timestamp": timestamp,
        "sessionId": session_id,
        "message": {"role": "assistant", "content": content},
    }


def _tool_result_msg():
    return {"type": "tool_result", "timestamp": "2026-03-31T00:02:00Z"}


def _snapshot_msg():
    return {"type": "file-history-snapshot", "timestamp": "2026-03-31T00:00:00Z"}


# ---------------------------------------------------------------------------
# 1. find_session_files
# ---------------------------------------------------------------------------


class TestFindSessionFiles(unittest.TestCase):

    def test_finds_jsonl_in_explicit_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path1 = os.path.join(tmpdir, "session-abc.jsonl")
            path2 = os.path.join(tmpdir, "session-def.jsonl")
            open(path1, "w").close()
            open(path2, "w").close()
            found = find_session_files(project_path=tmpdir)
            self.assertEqual(sorted(found), sorted([path1, path2]))

    def test_ignores_non_jsonl_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, "session.json"), "w").close()
            open(os.path.join(tmpdir, "session.txt"), "w").close()
            open(os.path.join(tmpdir, "session.jsonl"), "w").close()
            found = find_session_files(project_path=tmpdir)
            self.assertEqual(len(found), 1)
            self.assertTrue(found[0].endswith(".jsonl"))

    def test_returns_empty_list_for_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            found = find_session_files(project_path=tmpdir)
            self.assertEqual(found, [])

    def test_returns_sorted_list(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for name in ["c.jsonl", "a.jsonl", "b.jsonl"]:
                open(os.path.join(tmpdir, name), "w").close()
            found = find_session_files(project_path=tmpdir)
            self.assertEqual(found, sorted(found))


# ---------------------------------------------------------------------------
# 2. extract_signal — filtering
# ---------------------------------------------------------------------------


class TestExtractSignalFiltering(unittest.TestCase):

    def test_skips_tool_result_messages(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps(_tool_result_msg()) + "\n")
            path = f.name
        try:
            result = extract_signal(path)
            self.assertEqual(result, [])
        finally:
            os.unlink(path)

    def test_skips_file_history_snapshot(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write(json.dumps(_snapshot_msg()) + "\n")
            path = f.name
        try:
            result = extract_signal(path)
            self.assertEqual(result, [])
        finally:
            os.unlink(path)

    def test_skips_blank_lines(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write("\n\n")
            f.write(json.dumps(_user_msg("hello")) + "\n")
            path = f.name
        try:
            result = extract_signal(path)
            self.assertEqual(len(result), 1)
        finally:
            os.unlink(path)

    def test_skips_invalid_json_lines(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            f.write("this is not json\n")
            f.write(json.dumps(_user_msg("valid")) + "\n")
            path = f.name
        try:
            result = extract_signal(path)
            self.assertEqual(len(result), 1)
            self.assertEqual(result[0]["text"], "valid")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 3. extract_signal — user messages
# ---------------------------------------------------------------------------


class TestExtractSignalUserMessages(unittest.TestCase):

    def _run(self, messages):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            for m in messages:
                f.write(json.dumps(m) + "\n")
            path = f.name
        try:
            return extract_signal(path)
        finally:
            os.unlink(path)

    def test_extracts_user_text_from_content_block(self):
        result = self._run([_user_msg("what is the meaning of life")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "user")
        self.assertIn("meaning of life", result[0]["text"])

    def test_user_string_content(self):
        msg = {
            "type": "user",
            "timestamp": "2026-03-31T00:00:00Z",
            "message": {"role": "user", "content": "plain string content"},
        }
        result = self._run([msg])
        self.assertEqual(result[0]["text"], "plain string content")

    def test_user_multiple_text_blocks_joined(self):
        msg = {
            "type": "user",
            "timestamp": "2026-03-31T00:00:00Z",
            "message": {
                "role": "user",
                "content": [
                    {"type": "text", "text": "first"},
                    {"type": "text", "text": "second"},
                ],
            },
        }
        result = self._run([msg])
        self.assertIn("first", result[0]["text"])
        self.assertIn("second", result[0]["text"])

    def test_timestamp_preserved(self):
        result = self._run([_user_msg("hi", timestamp="2026-01-15T12:00:00Z")])
        self.assertEqual(result[0]["timestamp"], "2026-01-15T12:00:00Z")


# ---------------------------------------------------------------------------
# 4. extract_signal — assistant messages
# ---------------------------------------------------------------------------


class TestExtractSignalAssistantMessages(unittest.TestCase):

    def _run(self, messages):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            for m in messages:
                f.write(json.dumps(m) + "\n")
            path = f.name
        try:
            return extract_signal(path)
        finally:
            os.unlink(path)

    def test_extracts_assistant_text(self):
        result = self._run([_assistant_msg(text="Here is my analysis.")])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["role"], "assistant")
        self.assertIn("analysis", result[0]["text"])

    def test_extracts_thinking_block_truncated(self):
        long_thought = "A" * 1000
        result = self._run([_assistant_msg(thoughts=[long_thought])])
        self.assertIn("thoughts", result[0])
        self.assertLessEqual(len(result[0]["thoughts"][0]), 500)

    def test_short_thought_not_truncated(self):
        result = self._run([_assistant_msg(thoughts=["short thought"])])
        self.assertEqual(result[0]["thoughts"][0], "short thought")

    def test_empty_thought_not_included(self):
        msg = _assistant_msg(text="response")
        msg["message"]["content"].append({"type": "thinking", "thinking": ""})
        result = self._run([msg])
        self.assertNotIn("thoughts", result[0])

    def test_extracts_tool_use_action(self):
        result = self._run([_assistant_msg(tools=[{"name": "Bash", "input": {"command": "ls -la"}}])])
        self.assertIn("actions", result[0])
        self.assertEqual(result[0]["actions"][0]["tool"], "Bash")
        self.assertIn("ls -la", result[0]["actions"][0]["intent"])

    def test_tool_intent_truncated_at_200(self):
        long_input = {"command": "x" * 500}
        result = self._run([_assistant_msg(tools=[{"name": "Bash", "input": long_input}])])
        self.assertLessEqual(len(result[0]["actions"][0]["intent"]), 200)

    def test_assistant_with_no_content_not_included(self):
        msg = {
            "type": "assistant",
            "timestamp": "2026-03-31T00:00:00Z",
            "message": {"role": "assistant", "content": []},
        }
        result = self._run([msg])
        self.assertEqual(result, [])

    def test_assistant_non_list_content_skipped(self):
        msg = {
            "type": "assistant",
            "timestamp": "2026-03-31T00:00:00Z",
            "message": {"role": "assistant", "content": "raw string"},
        }
        result = self._run([msg])
        self.assertEqual(result, [])


# ---------------------------------------------------------------------------
# 5. extract_signal — error handling
# ---------------------------------------------------------------------------


class TestExtractSignalErrors(unittest.TestCase):

    def test_returns_error_string_for_missing_file(self):
        result = extract_signal("/nonexistent/path/session.jsonl")
        self.assertIsInstance(result, str)
        self.assertIn("Extraction Error", result)

    def test_returns_empty_list_for_empty_file(self):
        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            path = f.name
        try:
            result = extract_signal(path)
            self.assertEqual(result, [])
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------
# 6. skeleton_to_markdown
# ---------------------------------------------------------------------------


class TestSkeletonToMarkdown(unittest.TestCase):

    def test_contains_session_id_in_frontmatter(self):
        md = skeleton_to_markdown([], "my-session-123")
        self.assertIn("Session: my-session-123", md)

    def test_user_turn_formatted(self):
        skeleton = [{"role": "user", "timestamp": "2026-03-31T10:00:00Z", "text": "Hello world"}]
        md = skeleton_to_markdown(skeleton, "s1")
        self.assertIn("## USER", md)
        self.assertIn("Hello world", md)

    def test_assistant_turn_formatted(self):
        skeleton = [{"role": "assistant", "timestamp": "2026-03-31T10:01:00Z", "text": "Here is my response."}]
        md = skeleton_to_markdown(skeleton, "s1")
        self.assertIn("## A.I.M.", md)
        self.assertIn("Here is my response.", md)

    def test_thoughts_rendered_as_blockquote(self):
        skeleton = [{"role": "assistant", "timestamp": "t", "text": "", "thoughts": ["I think therefore I am"]}]
        md = skeleton_to_markdown(skeleton, "s1")
        self.assertIn("Internal Monologue", md)
        self.assertIn("I think therefore I am", md)

    def test_thought_truncated_at_200_in_markdown(self):
        long_thought = "T" * 500
        skeleton = [{"role": "assistant", "timestamp": "t", "text": "", "thoughts": [long_thought]}]
        md = skeleton_to_markdown(skeleton, "s1")
        # The markdown renderer truncates to 200
        self.assertNotIn("T" * 201, md)

    def test_actions_rendered_as_list(self):
        skeleton = [{
            "role": "assistant",
            "timestamp": "t",
            "text": "",
            "actions": [{"tool": "Read", "intent": "{'file': 'main.py'}"}],
        }]
        md = skeleton_to_markdown(skeleton, "s1")
        self.assertIn("Tools Executed", md)
        self.assertIn("`Read`", md)
        self.assertIn("main.py", md)

    def test_empty_skeleton_produces_valid_markdown(self):
        md = skeleton_to_markdown([], "empty-session")
        self.assertIn("# A.I.M. Signal Skeleton", md)

    def test_separator_between_turns(self):
        skeleton = [
            {"role": "user", "timestamp": "t1", "text": "Q"},
            {"role": "assistant", "timestamp": "t2", "text": "A"},
        ]
        md = skeleton_to_markdown(skeleton, "s1")
        self.assertGreaterEqual(md.count("---"), 2)


# ---------------------------------------------------------------------------
# 7. Compression ratio (integration-style)
# ---------------------------------------------------------------------------


class TestCompressionRatio(unittest.TestCase):
    """
    The stated goal of extract_signal is 9.3x compression.
    This test constructs a realistic session with heavy tool output and verifies
    that the extracted signal is substantially smaller than the raw input.
    """

    def test_signal_is_smaller_than_raw(self):
        messages = []

        # Simulate 5 user/assistant exchanges with tool calls
        for i in range(5):
            messages.append(_user_msg(f"Can you do task {i}?", timestamp=f"2026-03-31T0{i}:00:00Z"))
            messages.append(_assistant_msg(
                text=f"Sure, executing task {i}.",
                thoughts=[f"I need to think about task {i} carefully. " * 10],
                tools=[{"name": "Bash", "input": {"command": f"echo task{i}"}}],
                timestamp=f"2026-03-31T0{i}:01:00Z",
            ))
            # Tool result — should be filtered out entirely
            messages.append({
                "type": "tool_result",
                "timestamp": f"2026-03-31T0{i}:02:00Z",
                "message": {"content": [{"type": "text", "text": "x" * 5000}]},
            })

        with tempfile.NamedTemporaryFile(suffix=".jsonl", mode="w", delete=False) as f:
            for m in messages:
                f.write(json.dumps(m) + "\n")
            path = f.name

        try:
            raw_size = os.path.getsize(path)
            signal = extract_signal(path)
            signal_size = len(json.dumps(signal))
            self.assertLess(signal_size, raw_size,
                            f"Signal ({signal_size}b) should be smaller than raw ({raw_size}b)")
            ratio = raw_size / signal_size
            self.assertGreater(ratio, 2.0,
                               f"Expected compression ratio > 2x, got {ratio:.1f}x")
        finally:
            os.unlink(path)


# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
