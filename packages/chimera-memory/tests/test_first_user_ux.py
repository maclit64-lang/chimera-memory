"""Tests for first-user quickstart UX."""

from chimera_memory.cli import main


def test_quickstart_exits_zero(capsys) -> None:
    ret = main(["quickstart"])
    assert ret == 0


def test_quickstart_contains_init(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out
    assert "chimera-memory init" in out


def test_quickstart_contains_wrap(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out
    assert "chimera-memory wrap" in out


def test_quickstart_contains_verify(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out
    assert "chimera-memory verify" in out


def test_quickstart_contains_receipt_bundle(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out
    assert "receipt bundle" in out


def test_quickstart_contains_bundle_inspect(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out
    assert "bundle inspect" in out


def test_quickstart_no_m2b_scoring_claim(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out.lower()
    assert "m2b scoring" in out  # mentioned as not built
    assert "not built" in out


def test_quickstart_no_overclaim(capsys) -> None:
    main(["quickstart"])
    out = capsys.readouterr().out.lower()
    assert "m2b scoring is built" not in out
    assert "model ranking is built" not in out
    assert "routing is built" not in out


def test_init_shows_next_steps(tmp_path, monkeypatch, capsys) -> None:
    (tmp_path / ".git").mkdir()
    monkeypatch.chdir(tmp_path)
    main(["init"])
    out = capsys.readouterr().out
    assert "Next steps" in out
    assert "chimera-memory wrap" in out
    assert "chimera-memory quickstart" in out
