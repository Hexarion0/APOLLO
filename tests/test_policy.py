import json
from pathlib import Path
from apollo.policy import PermissionTier, PolicyEngine

def test_policy_engine_load_file(tmp_path: Path):
    policy_file = tmp_path / "policy.json"
    policy_data = {
        "version": "1.0",
        "default_tier": "confirm",
        "tools": {
            "get_system_info": "auto",
            "read_file": "logged",
            "execute_command": "confirm",
        },
    }
    policy_file.write_text(json.dumps(policy_data), encoding="utf-8")

    engine = PolicyEngine(policy_path=policy_file)
    assert engine.get_tier("get_system_info") == PermissionTier.AUTO
    assert engine.get_tier("read_file") == PermissionTier.LOGGED
    assert engine.get_tier("execute_command") == PermissionTier.CONFIRM
    # Unlisted tools fall back to default_tier (confirm)
    assert engine.get_tier("unknown_destructive_tool") == PermissionTier.CONFIRM

def test_policy_engine_fallback():
    engine = PolicyEngine(policy_path=Path("non_existent_policy.json"))
    assert engine.get_tier("any_tool") == PermissionTier.CONFIRM
