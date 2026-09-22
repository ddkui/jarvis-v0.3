"""Local web dashboard for voice settings - `delphi dashboard`.

A small Flask app, bound to 127.0.0.1 only (never exposed to the network - it has
no authentication, and accepts file uploads and freeform text). Reads/writes the
same delphi/settings.py store that delphi chat --speak reads from, so there's one
source of truth: no separate config path to keep in sync.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import litellm
from flask import Flask, after_this_request, jsonify, render_template, request, send_file

from delphi import runtime, settings as voice_settings, tts
from delphi.config import DelphiConfig
from delphi.models import AgentAbort


def _summarize(e: Exception) -> str:
    # litellm embeds a full traceback in some exceptions' message text; show only
    # the first line so error responses stay readable.
    return str(e).splitlines()[0]


def _delete_best_effort(path: Path) -> None:
    # On Windows, a file the WSGI server is still streaming out (e.g. via
    # send_file) can still be open when this runs, and deleting an open file
    # raises PermissionError there (POSIX allows it). This is just temp-file
    # cleanup, not correctness-critical, so a failed delete is fine to ignore -
    # the OS temp dir reclaims it eventually.
    try:
        path.unlink(missing_ok=True)
    except PermissionError:
        pass


def create_app(config: DelphiConfig) -> Flask:
    app = Flask(__name__)
    vault_dir = config.vault_dir
    app.config["VAULT_DIR"] = vault_dir
    state = {"agent": None}

    def _get_agent():
        if state["agent"] is None:
            state["agent"] = runtime.build_agent(config)
        return state["agent"]

    @app.get("/")
    def index():
        s = voice_settings.load_settings(vault_dir)
        return render_template(
            "dashboard.html",
            settings=s,
            voice_available=tts.is_enabled(),
            exaggeration_range=voice_settings.EXAGGERATION_RANGE,
            cfg_weight_range=voice_settings.CFG_WEIGHT_RANGE,
            speaking_rate_range=voice_settings.SPEAKING_RATE_RANGE,
        )

    @app.post("/settings")
    def update_settings():
        s = voice_settings.load_settings(vault_dir)
        active_voice = request.form.get("active_voice") or None
        if active_voice is not None and active_voice not in s.voices:
            return jsonify({"ok": False, "error": f"Unknown voice: {active_voice}"}), 400
        s.active_voice = active_voice
        try:
            s.exaggeration = voice_settings.clamp(
                float(request.form.get("exaggeration", s.exaggeration)), voice_settings.EXAGGERATION_RANGE
            )
            s.cfg_weight = voice_settings.clamp(
                float(request.form.get("cfg_weight", s.cfg_weight)), voice_settings.CFG_WEIGHT_RANGE
            )
            s.speaking_rate = voice_settings.clamp(
                float(request.form.get("speaking_rate", s.speaking_rate)), voice_settings.SPEAKING_RATE_RANGE
            )
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "exaggeration/cfg_weight/speaking_rate must be numbers"}), 400
        voice_settings.save_settings(vault_dir, s)
        return jsonify({"ok": True})

    @app.post("/voices")
    def upload_voice():
        name = (request.form.get("name") or "").strip()
        file = request.files.get("file")
        if not name or file is None or not file.filename:
            return jsonify({"ok": False, "error": "name and file are required"}), 400
        with tempfile.NamedTemporaryFile(suffix=Path(file.filename).suffix or ".wav", delete=False) as tmp:
            file.save(tmp.name)
            tmp_path = Path(tmp.name)
        try:
            voice_settings.add_voice(vault_dir, name, tmp_path)
        except ValueError as e:
            return jsonify({"ok": False, "error": str(e)}), 400
        finally:
            tmp_path.unlink(missing_ok=True)
        return jsonify({"ok": True})

    @app.post("/voices/<name>/delete")
    def delete_voice(name: str):
        ok = voice_settings.remove_voice(vault_dir, name)
        return jsonify({"ok": ok})

    @app.post("/preview")
    def preview():
        text = request.form.get("text") or "Hello, I'm Delphi. This is a preview of the current voice settings."
        try:
            tts.ensure_ready()
        except tts.VoiceUnavailable as e:
            return jsonify({"ok": False, "error": str(e)}), 400

        # Preview the form's current (possibly unsaved) slider/voice values, not
        # whatever was last saved to disk - that's the whole point of a preview.
        saved = voice_settings.load_settings(vault_dir)
        active_voice = request.form.get("active_voice") or None
        try:
            preview_settings = voice_settings.VoiceSettings(
                active_voice=active_voice,
                exaggeration=voice_settings.clamp(
                    float(request.form.get("exaggeration", saved.exaggeration)),
                    voice_settings.EXAGGERATION_RANGE,
                ),
                cfg_weight=voice_settings.clamp(
                    float(request.form.get("cfg_weight", saved.cfg_weight)), voice_settings.CFG_WEIGHT_RANGE
                ),
                speaking_rate=voice_settings.clamp(
                    float(request.form.get("speaking_rate", saved.speaking_rate)),
                    voice_settings.SPEAKING_RATE_RANGE,
                ),
                voices=saved.voices,
            )
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "exaggeration/cfg_weight/speaking_rate must be numbers"}), 400

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            out_path = Path(tmp.name)
        try:
            tts.synthesize(text, out_path, vault_dir, settings=preview_settings)
        except tts.VoiceUnavailable as e:
            _delete_best_effort(out_path)
            return jsonify({"ok": False, "error": str(e)}), 400

        @after_this_request
        def _cleanup(response):
            _delete_best_effort(out_path)
            return response

        return send_file(out_path, mimetype="audio/wav", download_name="preview.wav")

    @app.get("/chat")
    def chat_page():
        return render_template("chat.html", model=config.model)

    @app.get("/chat/history")
    def chat_history():
        agent = _get_agent()
        turns = []
        for m in agent.messages:
            role, content = m.get("role"), m.get("content")
            if role == "user" and isinstance(content, str):
                turns.append({"role": "you", "text": content})
            elif role == "assistant" and isinstance(content, str) and content:
                turns.append({"role": "delphi", "text": content})
        return jsonify({"ok": True, "turns": turns})

    @app.post("/chat/send")
    def chat_send():
        message = (request.form.get("message") or "").strip()
        if not message:
            return jsonify({"ok": False, "error": "message must not be empty"}), 400

        agent = _get_agent()
        try:
            reply = agent.send(message)
        except AgentAbort as e:
            runtime.save_conversation(config, agent)
            return jsonify({"ok": False, "error": f"Stopped: {e}"}), 200
        except (litellm.exceptions.AuthenticationError, litellm.exceptions.APIConnectionError) as e:
            return jsonify(
                {
                    "ok": False,
                    "error": f"Couldn't authenticate with the API for model '{config.model}': {_summarize(e)}. "
                    "Run `delphi auth set <KEY>` or check .env.",
                }
            ), 200
        except (litellm.exceptions.NotFoundError, litellm.exceptions.BadRequestError) as e:
            return jsonify(
                {"ok": False, "error": f"Couldn't reach model '{config.model}': {_summarize(e)}"}
            ), 200
        except Exception as e:
            return jsonify({"ok": False, "error": f"That turn hit a problem: {_summarize(e)}"}), 200
        runtime.save_conversation(config, agent)
        return jsonify({"ok": True, "reply": reply})

    @app.post("/chat/reset")
    def chat_reset():
        from delphi import conversation

        state["agent"] = None
        conversation.clear(vault_dir)
        return jsonify({"ok": True})

    return app


def run_dashboard(config: DelphiConfig, port: int = 8734, open_browser: bool = True) -> None:
    import threading
    import webbrowser

    from delphi import autoupdate

    autoupdate.check_once_and_restart_if_updated()
    autoupdate.run_background()

    app = create_app(config)
    url = f"http://127.0.0.1:{port}"
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    app.run(host="127.0.0.1", port=port, debug=False)
