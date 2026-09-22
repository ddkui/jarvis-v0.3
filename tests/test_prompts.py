from jarvis.agent.prompts import SYSTEM_PROMPT, build_system_prompt


def test_build_system_prompt_returns_base_when_no_facts():
    assert build_system_prompt([]) == SYSTEM_PROMPT


def test_build_system_prompt_appends_facts():
    prompt = build_system_prompt(["The user's name is Dan.", "Prefers concise answers."])

    assert prompt.startswith(SYSTEM_PROMPT)
    assert "The user's name is Dan." in prompt
    assert "Prefers concise answers." in prompt
    assert "- The user's name is Dan." in prompt
