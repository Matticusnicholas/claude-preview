"""Headless smoke test for claude_preview (Agent SDK edition).

Does NOT make a real agent call (that needs a login and spends credits).
It verifies the app mounts, the workspace/folder logic works, file previews
open, and the diff helper renders.
"""
import asyncio
import tempfile
from pathlib import Path

from claude_preview import ClaudePreviewApp, diff_text, renderable_for_path


def test_helpers():
    d = diff_text("a.py", "x = 1\n", "x = 2\n")
    assert "x = 1" in d.plain and "x = 2" in d.plain
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "hello.py"
        f.write_text("print('hi')\n", encoding="utf-8")
        r = renderable_for_path(f)
        assert r is not None
    print("helpers OK")


async def test_app_mounts():
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
        (proj / "notes.md").write_text("# Notes\n", encoding="utf-8")

        app = ClaudePreviewApp(workspace=str(proj))
        async with app.run_test(size=(130, 42)) as pilot:
            await pilot.pause()
            assert app.workspace == proj.resolve()
            # open a file tab programmatically (simulates clicking the tree)
            app.open_file_tab(proj / "main.py")
            await pilot.pause()
            from textual.widgets import TabbedContent
            tabs = app.query_one("#preview-tabs", TabbedContent)
            assert tabs.get_pane("file-" + _slug(proj / "main.py")) is not None
            # simulate the agent reporting an edit -> Changes log
            app.record_change("Edit", {
                "file_path": str(proj / "main.py"),
                "old_string": "print('hello')",
                "new_string": "print('hello world')",
            })
            await pilot.pause()
            # workspace switch closes stale tabs and resets
            app.set_workspace(td)
            await pilot.pause()
            # keybinding: reload tree
            await pilot.press("ctrl+r")
            await pilot.pause()
    print("app mount + folder + previews OK")


def _slug(path: Path) -> str:
    import re
    return re.sub(r"[^A-Za-z0-9_-]", "-", str(path))


if __name__ == "__main__":
    test_helpers()
    asyncio.run(test_app_mounts())
    print("ALL SMOKE TESTS PASSED")
