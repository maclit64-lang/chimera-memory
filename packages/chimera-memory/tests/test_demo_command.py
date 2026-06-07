"""Tests for chimera-memory demo command."""

from pathlib import Path

from chimera_memory.cli import main


def test_demo_exits_zero(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo"
    ret = main(["demo", "--output-dir", str(out_dir)])
    assert ret == 0


def test_demo_creates_receipt(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo"
    main(["demo", "--output-dir", str(out_dir)])
    assert (out_dir / "receipt").is_dir()
    assert (out_dir / "receipt" / "receipt.json").exists()
    assert (out_dir / "receipt" / "README.md").exists()


def test_demo_creates_workspace(tmp_path: Path) -> None:
    out_dir = tmp_path / "demo"
    main(["demo", "--output-dir", str(out_dir)])
    assert (out_dir / "workspace").is_dir()
    assert (out_dir / "workspace" / ".chimera-memory").is_dir()


def test_demo_does_not_touch_cwd(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    out_dir = tmp_path / "demo-out"
    main(["demo", "--output-dir", str(out_dir)])
    assert not (tmp_path / ".chimera-memory").exists()


def test_demo_refuses_nonempty_dir(tmp_path: Path) -> None:
    out_dir = tmp_path / "nonempty"
    out_dir.mkdir()
    (out_dir / "file.txt").write_text("x")
    ret = main(["demo", "--output-dir", str(out_dir)])
    assert ret == 1


def test_demo_output_mentions_next(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "demo"
    main(["demo", "--output-dir", str(out_dir)])
    out = capsys.readouterr().out
    assert "quickstart" in out
    assert "bundle inspect" in out


def test_demo_no_overclaim(tmp_path: Path, capsys) -> None:
    out_dir = tmp_path / "demo"
    main(["demo", "--output-dir", str(out_dir)])
    out = capsys.readouterr().out.lower()
    assert "m2b scoring is built" not in out
    assert "model ranking is built" not in out
