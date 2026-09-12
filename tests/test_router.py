"""Tests for the adaptive ComplexityRouter."""

import pytest

from apollo.providers.router import ComplexityRouter, ModelTier
from apollo.config import ProviderConfig


@pytest.fixture
def router():
    config = ProviderConfig(
        api_key="test",
        model_fast="nvidia/nemotron-3-super-120b-a12b",
        model_balanced="nvidia/nemotron-4-340b-instruct",
        model_complex="nvidia/nemotron-3-ultra-550b-a55b",
    )
    return ComplexityRouter(config=config)


# ---------------------------------------------------------------------------
# Fast tier — pattern matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "what's the time",
    "what is the time",
    "current time",
    "What time is it now",
    "play next song",
    "pause",
    "skip track",
    "volume up",
    "hi",
    "hello",
    "hey",
    "good morning",
    "what's the weather",
    "weather today",
    "remind me to call John at 5pm",
    "set a reminder for tomorrow",
    "lock pc",
    "screen off",
    "ping",
    "status",
])
def test_fast_patterns(router, prompt):
    tier, _ = router.classify(prompt)
    assert tier == ModelTier.FAST, f"Expected FAST for '{prompt}', got {tier}"


# ---------------------------------------------------------------------------
# Complex tier — pattern matching
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "deeply think about the architecture of this distributed system",
    "architectural design of a new microservices platform",
    "refactor the entire codebase to use async patterns",
    "step-by-step tradeoff analysis between gRPC and REST",
    "formulate a mathematical proof for this algorithm",
    "full implementation plan for the authentication system",
])
def test_complex_patterns(router, prompt):
    tier, _ = router.classify(prompt)
    assert tier == ModelTier.COMPLEX, f"Expected COMPLEX for '{prompt}', got {tier}"


# ---------------------------------------------------------------------------
# Balanced tier — default for technical / coding queries
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prompt", [
    "write a Python function to parse JSON",
    "explain how async/await works in JavaScript",
    "fix the bug in this function",
    "what is a decorator in Python",
    "can you run git status",
    "list the files in my project",
])
def test_balanced_patterns(router, prompt):
    tier, _ = router.classify(prompt)
    assert tier == ModelTier.BALANCED, f"Expected BALANCED for '{prompt}', got {tier}"


# ---------------------------------------------------------------------------
# Manual prefix overrides
# ---------------------------------------------------------------------------

def test_fast_prefix_slash(router):
    tier, cleaned = router.classify("/fast what is 2+2")
    assert tier == ModelTier.FAST
    assert cleaned == "what is 2+2"


def test_fast_prefix_bracket(router):
    tier, cleaned = router.classify("[fast] quick question")
    assert tier == ModelTier.FAST
    assert cleaned == "quick question"


def test_fast_prefix_bang(router):
    tier, cleaned = router.classify("!fast tell me the time")
    assert tier == ModelTier.FAST


def test_complex_prefix_deep(router):
    tier, cleaned = router.classify("/deep analyze this architecture")
    assert tier == ModelTier.COMPLEX
    assert cleaned == "analyze this architecture"


def test_complex_prefix_ultra(router):
    tier, _ = router.classify("/ultra solve this")
    assert tier == ModelTier.COMPLEX


def test_complex_prefix_bang_deep(router):
    tier, _ = router.classify("!deep think about this")
    assert tier == ModelTier.COMPLEX


def test_balanced_prefix(router):
    tier, cleaned = router.classify("/balanced write a function")
    assert tier == ModelTier.BALANCED
    assert cleaned == "write a function"


def test_mid_prefix(router):
    tier, _ = router.classify("/mid do this")
    assert tier == ModelTier.BALANCED


# ---------------------------------------------------------------------------
# Model string resolution
# ---------------------------------------------------------------------------

def test_get_model_fast(router):
    model = router.get_model_for_prompt("what's the time")
    assert model == "nvidia/nemotron-3-super-120b-a12b"


def test_get_model_balanced(router):
    model = router.get_model_for_prompt("write me a REST API in Python")
    assert model == "nvidia/nemotron-4-340b-instruct"


def test_get_model_complex(router):
    model = router.get_model_for_prompt("deeply think about distributed system architecture design")
    assert model == "nvidia/nemotron-3-ultra-550b-a55b"


def test_get_model_override_prefix(router):
    model = router.get_model_for_prompt("/fast write me a novel")
    assert model == "nvidia/nemotron-3-super-120b-a12b"


# ---------------------------------------------------------------------------
# Length heuristic (>1500 chars + 2+ code blocks → complex)
# ---------------------------------------------------------------------------

def test_length_heuristic_complex(router):
    long_prompt = "Here is a large request.\n" + "```python\nx = 1\n```\n" * 10 + "a" * 1600
    tier, _ = router.classify(long_prompt)
    assert tier == ModelTier.COMPLEX


def test_length_heuristic_no_code_blocks_stays_balanced(router):
    long_prompt = "a" * 1600  # long but no code blocks
    tier, _ = router.classify(long_prompt)
    assert tier == ModelTier.BALANCED


# ---------------------------------------------------------------------------
# No-config fallback (router created without explicit ProviderConfig)
# ---------------------------------------------------------------------------

def test_router_no_config_defaults():
    router = ComplexityRouter()
    model = router.get_model_for_prompt("what's the time")
    assert model == "nvidia/nemotron-3-super-120b-a12b"

    model = router.get_model_for_prompt("deeply think about architecture")
    assert model == "nvidia/nemotron-3-ultra-550b-a55b"
