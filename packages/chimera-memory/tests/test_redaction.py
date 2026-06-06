"""Tests for CHM-2 witness redaction."""

from __future__ import annotations

from chimera_memory.redaction import redact

# ---------------------------------------------------------------------------
# Unit tests for the redact function
# ---------------------------------------------------------------------------


def test_redact_leaves_clean_output_unchanged() -> None:
    text = "All tests passed: 42/42\nNo issues found."
    assert redact(text) == text


def test_redact_none_returns_empty() -> None:
    assert redact(None) == ""


def test_redact_empty_string() -> None:
    assert redact("") == ""


def test_redact_bearer_token() -> None:
    text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.fake"
    result = redact(text)
    assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in result
    assert "REDACTED" in result


def test_redact_github_token() -> None:
    text = "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
    result = redact(text)
    assert "ghp_" not in result
    assert "REDACTED" in result


def test_redact_openai_key() -> None:
    text = "using key sk-abcdefghijklmnopqrstuvwxyz123456789"
    result = redact(text)
    assert "sk-abcdefghijklmnopqrstuvwxyz123456789" not in result
    assert "REDACTED" in result


def test_redact_aws_access_key() -> None:
    text = "AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE"
    result = redact(text)
    assert "AKIAIOSFODNN7EXAMPLE" not in result
    assert "REDACTED" in result


def test_redact_slack_token() -> None:
    text = "slack_token = xoxb-1234567890-abcdefghijklmnop"
    result = redact(text)
    assert "xoxb-" not in result
    assert "REDACTED" in result


def test_redact_db_url() -> None:
    text = "DATABASE_URL=postgresql://alice:s3cr3tpass@db.example.com/mydb"
    result = redact(text)
    assert "s3cr3tpass" not in result
    assert "REDACTED" in result


def test_redact_password_assignment() -> None:
    text = "password=supersecretvalue123"
    result = redact(text)
    assert "supersecretvalue123" not in result
    assert "REDACTED" in result


def test_redact_api_key_assignment() -> None:
    text = "api_key=abcdef1234567890abcdef"
    result = redact(text)
    assert "abcdef1234567890abcdef" not in result
    assert "REDACTED" in result


# ---------------------------------------------------------------------------
# Integration tests: redaction flows through wrap → storage → export/receipt
# ---------------------------------------------------------------------------


def test_redaction_in_stored_claim(tmp_path) -> None:
    """Secrets wrapped via CLI are redacted before storage in claim metadata."""
    from datetime import UTC, datetime

    from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

    from chimera_memory.ledger import record_claim, settle_claim
    from chimera_memory.redaction import redact
    from chimera_memory.storage import MemoryStore

    fake_secret = "sk-TESTkeyABCDEFGHIJKLMNOPQRSTUVWXYZ"
    redacted_stdout = redact(f"output: {fake_secret}")
    assert fake_secret not in redacted_stdout

    t0 = datetime(2026, 6, 5, 10, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, tzinfo=UTC)
    claim_id = record_claim(
        title="redaction test",
        summary="testing secret redaction",
        predicted=True,
        evidence=[EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="test", available_at=t0)],
        root=tmp_path,
        claim_time=t0,
        agent_id="test-agent",
        task_type="test",
    )
    settle_claim(
        claim_id,
        True,
        t1,
        root=tmp_path,
        event_metadata={
            "stdout_excerpt": redacted_stdout,
            "stderr_excerpt": "",
        },
    )

    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(claim_id)
    assert claim is not None
    # Serialised claim must not contain the raw secret
    assert fake_secret not in str(claim.model_dump(mode="json"))


def test_export_does_not_contain_secret(tmp_path) -> None:
    """Export of a settled claim with redacted witness does not surface raw secret."""
    from datetime import UTC, datetime

    from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

    from chimera_memory.ledger import record_claim, settle_claim
    from chimera_memory.redaction import redact
    from chimera_memory.storage import MemoryStore

    fake_secret = "ghp_FakeGitHubTokenABCDEFGHIJKLMNOPQRST"
    stdout = redact(f"token={fake_secret}")
    assert fake_secret not in stdout

    t0 = datetime(2026, 6, 5, 10, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, tzinfo=UTC)
    claim_id = record_claim(
        title="export secret test",
        summary="no secrets in export",
        predicted=True,
        evidence=[EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="x", available_at=t0)],
        root=tmp_path,
        claim_time=t0,
        agent_id="agent",
        task_type="test",
    )
    settle_claim(claim_id, True, t1, root=tmp_path,
                 event_metadata={"stdout_excerpt": stdout, "stderr_excerpt": ""})

    store = MemoryStore(tmp_path / ".chimera-memory")
    claim = store.latest_claim(claim_id)
    assert claim is not None
    assert fake_secret not in str(claim.model_dump(mode="json"))


def test_receipt_command_display_redacts_args(tmp_path) -> None:
    """CHM-task3: fake secret in wrapped_args is redacted in receipt command display."""
    from datetime import UTC, datetime

    from chimera_memory_types.finding import EvidenceRef, EvidenceRefType

    from chimera_memory.ledger import record_claim, settle_claim
    from chimera_memory.receipt import build_receipt
    from chimera_memory.session import FinalStatus
    from chimera_memory.session_lifecycle import end_session, start_session
    from chimera_memory.storage import MemoryStore

    fake_secret = "sk-TESTfakeSecretArgABCDEFGHIJKLMNOPQ"
    t0 = datetime(2026, 6, 5, 10, tzinfo=UTC)
    t1 = datetime(2026, 6, 5, 11, tzinfo=UTC)

    sid = start_session(
        repo_path=tmp_path, branch="b", task_label="t", agent_app="a", model="m"
    )
    claim_id = record_claim(
        title="cmd-arg-redact test",
        summary="s",
        predicted=True,
        evidence=[EvidenceRef(ref_type=EvidenceRefType.EXTERNAL, ref_id="r", available_at=t0)],
        root=tmp_path,
        claim_time=t0,
        agent_id="a",
        task_type="test",
        extra_metadata={"session_id": sid},
    )
    settle_claim(
        claim_id, True, t1, root=tmp_path,
        event_metadata={
            "wrapped_args": ["python", "-c", f"token={fake_secret}"],
            "stdout_excerpt": "",
            "stderr_excerpt": "",
            "exit_code": 0,
        },
    )
    end_session(repo_path=tmp_path, final_status=FinalStatus.PASSED)

    store = MemoryStore(tmp_path / ".chimera-memory")
    session_data = store.get_session(sid)
    assert session_data is not None
    receipt = build_receipt(session_data, root=tmp_path)

    # The receipt command display must not contain the raw secret
    commands_str = str(receipt.get("commands_observed", ""))
    assert fake_secret not in commands_str
    assert "REDACTED" in commands_str
