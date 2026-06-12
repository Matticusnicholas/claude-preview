"""Headless smoke test for claude_preview using Textual's pilot."""
import asyncio

from claude_preview import ClaudePreviewApp, Workspace


def test_workspace_extraction():
    ws = Workspace()
    text = (
        "Here you go:\n\n"
        "```python app.py\nprint('hi')\n```\n\n"
        "and a snippet with no name:\n\n"
        "```js\nconsole.log(1)\n```\n"
        "and an unterminated streaming block:\n\n"
        "```python partial.py\nx = 1\n"
    )
    touched = ws.update_from_text(text)
    assert "app.py" in ws.files, ws.files
    assert ws.files["app.py"].content.strip() == "print('hi')"
    assert "snippet_1.js" in ws.files
    assert "partial.py" in ws.files, "streaming (unterminated) block not captured"
    print("workspace extraction OK:", touched)


async def test_app_mounts():
    app = ClaudePreviewApp()
    async with app.run_test(size=(120, 40)) as pilot:
        # App mounted; type /help and submit
        await pilot.click("#chat-input")
        for ch in "/help":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # /files with empty workspace
        for ch in "/files":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        # simulate an assistant message producing a file -> preview tab appears
        touched = app.apply_extracted("```python hello.py\nprint('hello world')\n```")
        await pilot.pause()
        assert touched == ["hello.py"]
        from textual.widgets import TabbedContent
        tabs = app.query_one("#preview-tabs", TabbedContent)
        assert tabs.get_pane("tab-hello-py") is not None
        # focus the tab via /preview
        await pilot.click("#chat-input")
        for ch in "/preview hello.py":
            await pilot.press(ch)
        await pilot.press("enter")
        await pilot.pause()
        assert tabs.active == "tab-hello-py", tabs.active
        # keybindings
        await pilot.press("ctrl+r")
        await pilot.pause()
    print("app mount + commands + preview tabs OK")


if __name__ == "__main__":
    test_workspace_extraction()
    asyncio.run(test_app_mounts())
    print("ALL SMOKE TESTS PASSED")
