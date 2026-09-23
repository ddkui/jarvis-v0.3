from delphi.tools import location_tools


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_LOCATION", raising=False)
    assert location_tools.build_tools() == []


def test_disabled_when_env_var_not_exactly_one(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_LOCATION", "true")
    assert location_tools.build_tools() == []


def test_enabled_exposes_get_location(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_LOCATION", "1")
    tools = _tools_by_name(location_tools.build_tools())
    assert set(tools) == {"get_location"}


def test_get_location_reports_city_region_country_and_timezone(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_LOCATION", "1")
    monkeypatch.setattr(
        location_tools,
        "_fetch_location",
        lambda: {
            "city": "Prague",
            "region": "Prague",
            "country_name": "Czechia",
            "timezone": "Europe/Prague",
        },
    )

    tools = _tools_by_name(location_tools.build_tools())
    result = tools["get_location"].handler({})

    assert "Prague" in result
    assert "Czechia" in result
    assert "Europe/Prague" in result


def test_get_location_handles_api_error_field(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_LOCATION", "1")
    monkeypatch.setattr(
        location_tools, "_fetch_location", lambda: {"error": True, "reason": "RateLimited"}
    )

    tools = _tools_by_name(location_tools.build_tools())
    result = tools["get_location"].handler({})

    assert "Couldn't determine location" in result
    assert "RateLimited" in result


def test_get_location_handles_network_failure(monkeypatch):
    monkeypatch.setenv("DELPHI_ENABLE_LOCATION", "1")

    def _raise():
        raise OSError("network unreachable")

    monkeypatch.setattr(location_tools, "_fetch_location", _raise)

    tools = _tools_by_name(location_tools.build_tools())
    result = tools["get_location"].handler({})

    assert "Couldn't determine location" in result
    assert "network unreachable" in result
