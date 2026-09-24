import pytest

import islandpulse.client


@pytest.fixture
def sleeps(monkeypatch):
    """Record retry sleeps instead of sleeping."""
    calls: list[float] = []
    monkeypatch.setattr(islandpulse.client.time, "sleep", calls.append)
    return calls
