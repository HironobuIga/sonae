import pytest

from sonae.config import settings


@pytest.fixture()
def tmp_store(tmp_path):
    """Isolate persistence and caching into the test's tmp dir."""
    old = (settings.data_dir, settings.cache_dir, settings.store_dir)
    settings.data_dir = tmp_path / "data"
    settings.cache_dir = tmp_path / "data" / "cache"
    settings.store_dir = tmp_path / "data" / "store"
    yield settings.store_dir
    settings.data_dir, settings.cache_dir, settings.store_dir = old


@pytest.fixture()
def offline():
    """Force bundled-resource mode (no network)."""
    old = settings.offline
    settings.offline = True
    yield
    settings.offline = old
