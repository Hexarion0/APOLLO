import pytest
from apollo.tools.internet import FetchURLTool, GetWeatherTool, WebSearchTool, _extract_ddg_url

def test_web_search_schema():
    tool = WebSearchTool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "web_search"
    assert "query" in schema["function"]["parameters"]["required"]

def test_fetch_url_schema():
    tool = FetchURLTool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "fetch_url"
    assert "url" in schema["function"]["parameters"]["required"]

def test_get_weather_schema():
    tool = GetWeatherTool()
    schema = tool.to_openai_schema()
    assert schema["type"] == "function"
    assert schema["function"]["name"] == "get_weather"
    assert "location" in schema["function"]["parameters"]["required"]

def test_extract_ddg_url():
    assert _extract_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com&rut=1") == "https://example.com"
    assert _extract_ddg_url("https://directlink.org") == "https://directlink.org"
    assert _extract_ddg_url("") == ""

@pytest.mark.asyncio
async def test_fetch_url_invalid_scheme():
    tool = FetchURLTool()
    with pytest.raises(ValueError, match="Invalid URL scheme"):
        await tool.execute(url="ftp://invalid.com")
