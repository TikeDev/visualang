import asyncio

from agents import tools


def test_rate_visualizability_handler_rejects_non_list(monkeypatch):
    async def fake_run_claude(**_):
        return '{"index": 0, "rating": 5, "issues": []}'

    monkeypatch.setattr(tools.base, "run_claude", fake_run_claude)

    result = asyncio.run(
        tools.rate_visualizability_handler(
            concepts=[{"index": 0, "concept": "x", "image_prompt": "y"}]
        )
    )

    assert result["ratings"] == []
    assert "error" in result


def test_rate_visualizability_handler_accepts_list(monkeypatch):
    async def fake_run_claude(**_):
        return '[{"index": 0, "rating": 5, "issues": []}]'

    monkeypatch.setattr(tools.base, "run_claude", fake_run_claude)

    result = asyncio.run(
        tools.rate_visualizability_handler(
            concepts=[{"index": 0, "concept": "x", "image_prompt": "y"}]
        )
    )

    assert result["ratings"] == [{"index": 0, "rating": 5, "issues": []}]
