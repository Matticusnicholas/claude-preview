"""Backend smoke test for the web server (no live agent call)."""
import sys
import tempfile
from pathlib import Path

# import the server module
sys.path.insert(0, str(Path(__file__).parent))
import server  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402


def run():
    with tempfile.TemporaryDirectory() as td:
        proj = Path(td)
        (proj / "main.py").write_text("print('hello')\n", encoding="utf-8")
        sub = proj / "src"
        sub.mkdir()
        (sub / "util.py").write_text("x = 1\n", encoding="utf-8")

        # point the session at the temp project
        import asyncio
        asyncio.get_event_loop().run_until_complete(server.SESSION.reset(str(proj)))

        client = TestClient(server.app)

        assert client.get("/").status_code == 200
        assert "<title>claude-preview</title>" in client.get("/").text

        st = client.get("/api/state").json()
        assert Path(st["workspace"]) == proj.resolve(), st

        tree = client.get("/api/tree").json()
        names = [c["name"] for c in tree["children"]]
        assert "main.py" in names and "src" in names, names

        sub_tree = client.get("/api/tree", params={"path": str(sub)}).json()
        assert any(c["name"] == "util.py" for c in sub_tree["children"])

        f = client.get("/api/file", params={"path": str(proj / "main.py")}).json()
        assert f["language"] == "python" and "hello" in f["content"]

        # save round-trip
        r = client.post("/api/save", json={"path": str(proj / "main.py"), "content": "print('hi2')\n"})
        assert r.json().get("ok")
        assert "hi2" in (proj / "main.py").read_text()

        # simulate a pending change via snapshot + accept/reject
        target = proj / "src" / "util.py"
        server.SESSION.snapshots[str(target.resolve())] = "x = 1\n"
        target.write_text("x = 2\n", encoding="utf-8")
        ch = client.get("/api/changes").json()
        assert any(i["rel"] == "src/util.py" and i["status"] == "modified" for i in ch["items"]), ch

        d = client.get("/api/diff", params={"path": str(target)}).json()
        assert d["original"] == "x = 1\n" and d["current"] == "x = 2\n"

        # reject -> restored
        client.post("/api/reject", json={"path": str(target)})
        assert target.read_text() == "x = 1\n"
        assert client.get("/api/changes").json()["items"] == []

        # new-file reject -> deleted
        newf = proj / "created.py"
        server.SESSION.snapshots[str(newf.resolve())] = None
        newf.write_text("# new\n", encoding="utf-8")
        client.post("/api/reject", json={"path": str(newf)})
        assert not newf.exists()

    print("WEB BACKEND SMOKE TESTS PASSED")


if __name__ == "__main__":
    run()
