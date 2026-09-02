import pytest
from apollo.persona import get_proactive_prompt_for_time, DEFAULT_PERSONA_PROMPT

def test_persona_prompt_content():
    assert "APOLLO" in DEFAULT_PERSONA_PROMPT
    assert "Personality" in DEFAULT_PERSONA_PROMPT

def test_proactive_prompt_generation():
    prompt = get_proactive_prompt_for_time()
    assert isinstance(prompt, str)
    assert len(prompt) > 10
