"""Smoke test: the whole app module loads (catches errors in code no other test imports)."""


def test_api_module_imports():
    import api

    assert api.app.routes
