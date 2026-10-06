import importlib
import os
import time

import pytest


@pytest.fixture(scope="session", autouse=True)
def _madrid_timezone():
    """The prototype builds naive local datetimes with fromtimestamp, so
    expected values depend on the machine's timezone. Pin the one the
    scraper runs in."""
    previous = os.environ.get("TZ")
    os.environ["TZ"] = "Europe/Madrid"
    time.tzset()
    yield
    if previous is None:
        del os.environ["TZ"]
    else:
        os.environ["TZ"] = previous
    time.tzset()


@pytest.fixture(scope="session")
def legacy_cwd(tmp_path_factory):
    """An empty working directory for the legacy modules.

    The watcher reads seen.json and the JSONL relative to the working
    directory at import time, so it must never be imported from a folder
    that holds real data.
    """
    path = tmp_path_factory.mktemp("legacy_cwd")
    previous = os.getcwd()
    os.chdir(path)
    yield path
    os.chdir(previous)


@pytest.fixture(scope="session")
def watcher(legacy_cwd):
    return importlib.import_module("wallabot.legacy.wallapop_watcher")


@pytest.fixture(scope="session")
def server(legacy_cwd):
    return importlib.import_module("wallabot.legacy.market_server")
