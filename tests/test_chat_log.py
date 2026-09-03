from pathlib import Path
from apollo.chat_log import ChatFileLogger

def test_chat_file_logger(tmp_path: Path):
    log_file = tmp_path / "chat.log"
    logger = ChatFileLogger(log_path=log_file)

    logger.log_user("Hello, APOLLO!", sender_id="12345")
    logger.log_tool_call("web_search", {"query": "weather"})
    logger.log_tool_result("web_search", {"results": []}, status="EXECUTED")
    logger.log_assistant("Hello! How can I help you today?")
    logger.log_session_end()

    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "SESSION START" in content
    assert "USER (12345)" in content
    assert "Hello, APOLLO!" in content
    assert "TOOL → web_search" in content
    assert "TOOL RESULT ← web_search [EXECUTED]" in content
    assert "APOLLO" in content
    assert "Hello! How can I help you today?" in content
    assert "SESSION END" in content
