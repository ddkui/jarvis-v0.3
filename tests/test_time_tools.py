from delphi.tools import time_tools


def _tools_by_name(tools):
    return {t.name: t for t in tools}


def test_always_available_no_env_var_needed(monkeypatch):
    monkeypatch.delenv("DELPHI_ENABLE_TIME", raising=False)
    tools = _tools_by_name(time_tools.build_tools())
    assert set(tools) == {"get_current_time"}


def test_get_current_time_includes_day_and_year():
    tools = _tools_by_name(time_tools.build_tools())
    result = tools["get_current_time"].handler({})

    from datetime import datetime

    now = datetime.now()
    assert str(now.year) in result
    assert now.strftime("%A") in result
