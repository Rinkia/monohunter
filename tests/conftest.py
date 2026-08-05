"""Slow-test gate: network integration tests (MAST/NASA) are opt-in.

Default `pytest` skips anything marked `slow`. Run them with `pytest --runslow`.
This keeps PR CI fast and offline while still allowing a real-data regression.
"""

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--runslow",
        action="store_true",
        default=False,
        help="run slow tests that hit the network (MAST / NASA archives)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "slow: hits the network (MAST / NASA archives); needs --runslow"
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="needs --runslow (network test)")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)
