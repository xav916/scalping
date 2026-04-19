"""Shared pytest fixtures for the Scalping Radar backend."""
import pytest
import pytest_asyncio


@pytest.fixture
def anyio_backend():
    return "asyncio"
