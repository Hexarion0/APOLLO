import json
from pathlib import Path
from apollo.audit import AuditLogger

def test_audit_logger_write_and_read(tmp_path: Path):
    log_file = tmp_path / "audit.log"
    logger = AuditLogger(log_path=log_file)

    entry = logger.log_action(
        tool_name="execute_command",
        arguments={"command": "ls -la"},
        tier="confirm",
        status="CONFIRMED",
        result={"exit_code": 0},
    )

    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1

    parsed = json.loads(lines[0])
    assert parsed["tool_name"] == "execute_command"
    assert parsed["tier"] == "confirm"
    assert parsed["status"] == "CONFIRMED"
    assert "timestamp" in parsed
