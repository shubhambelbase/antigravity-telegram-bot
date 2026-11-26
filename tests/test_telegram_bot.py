"""Unit and integration tests for Telegram Bot command handlers, auth, callbacks, and state persistence."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from telegram import Update

from execution import telegram_bot


def _make_update(user_id=12345, text="hello", callback_data=None):
    user = SimpleNamespace(id=user_id, username="tester")
    chat = SimpleNamespace(id=user_id)
    msg = MagicMock()
    msg.text = text
    msg.reply_text = AsyncMock()
    msg.reply_document = AsyncMock()
    msg.reply_photo = AsyncMock()

    if callback_data is not None:
        query = MagicMock()
        query.data = callback_data
        query.message = msg
        query.answer = AsyncMock()
        query.edit_message_text = AsyncMock()
        query.edit_message_reply_markup = AsyncMock()
        return SimpleNamespace(
            effective_user=user,
            effective_chat=chat,
            effective_message=msg,
            message=None,
            callback_query=query,
        )

    return SimpleNamespace(
        effective_user=user,
        effective_chat=chat,
        effective_message=msg,
        message=msg,
        callback_query=None,
    )


def _make_context(args=None):
    return SimpleNamespace(
        args=args or [],
        user_data={},
        application=SimpleNamespace(bot_data={}),
    )


def test_check_auth_handles_missing_message():
    async def _run():
        orig = set(telegram_bot.ALLOWED_USER_IDS)
        telegram_bot.ALLOWED_USER_IDS.clear()
        try:
            upd = SimpleNamespace(
                effective_user=SimpleNamespace(id=999, username="stranger"),
                effective_message=None,
                message=None,
            )
            ok = await telegram_bot.check_auth(upd)
            assert ok is False
        finally:
            telegram_bot.ALLOWED_USER_IDS.update(orig)

    asyncio.run(_run())


def test_claim_requires_valid_pin(monkeypatch, tmp_path):
    async def _run():
        env_file = tmp_path / ".env"
        env_file.write_text("TELEGRAM_BOT_TOKEN=tok\nALLOWED_TELEGRAM_USER_IDS=\n", encoding="utf-8")
        pin_file = tmp_path / "pairing_code.txt"

        monkeypatch.setattr(telegram_bot, "DOTENV_PATH", str(env_file))
        monkeypatch.setattr(telegram_bot, "PAIRING_CODE_FILE", str(pin_file))
        monkeypatch.setattr(telegram_bot, "ALLOWED_USER_IDS", set())
        monkeypatch.setattr(telegram_bot, "_active_pairing_pin", None)

        pin = telegram_bot.get_or_create_pairing_pin()
        assert len(pin) == 6
        assert pin_file.is_file()

        # Wrong PIN rejected
        upd_bad = _make_update(user_id=777)
        await telegram_bot.cmd_claim(upd_bad, _make_context(["000000"]))
        assert 777 not in telegram_bot.ALLOWED_USER_IDS
        assert "Pairing PIN Required" in upd_bad.message.reply_text.call_args.args[0]

        # Correct PIN accepted
        upd_ok = _make_update(user_id=777)
        await telegram_bot.cmd_claim(upd_ok, _make_context([pin]))
        assert 777 in telegram_bot.ALLOWED_USER_IDS
        assert "ALLOWED_TELEGRAM_USER_IDS=777" in env_file.read_text(encoding="utf-8")
        assert not pin_file.exists()

    asyncio.run(_run())


def test_cmd_stop_preserves_stream_until_confirmed(monkeypatch):
    async def _run():
        monkeypatch.setattr(telegram_bot, "ALLOWED_USER_IDS", {12345})
        monkeypatch.setattr(telegram_bot, "find_interactive_agy_pid", lambda **kw: 9876)
        monkeypatch.setattr(telegram_bot, "is_agy_process_busy", lambda pid: True)
        injected_keys = []
        monkeypatch.setattr(telegram_bot, "inject_special_key", lambda key, **kw: injected_keys.append(key) or True)

        mock_session = MagicMock()
        mock_session.is_active = True
        mock_session.cancel = AsyncMock()
        mock_mgr = MagicMock()
        mock_mgr.get_session.return_value = mock_session
        monkeypatch.setattr(telegram_bot, "stream_manager", mock_mgr)

        upd = _make_update(user_id=12345)
        await telegram_bot.cmd_stop(upd, _make_context([]))

        # Stream MUST remain active while waiting for user confirmation
        assert mock_session.cancel.await_count == 0
        assert injected_keys == []
        assert "actively executing" in upd.message.reply_text.call_args.args[0]

        # Confirming via inline button cancels stream and injects Ctrl+C
        upd_confirm = _make_update(user_id=12345, callback_data="key:ctrl_c_confirmed")
        await telegram_bot.handle_callback_query(upd_confirm, _make_context([]))
        assert mock_session.cancel.await_count == 1
        assert injected_keys == ["ctrl_c"]

    asyncio.run(_run())


def test_cmd_logs_checks_escaped_length(monkeypatch):
    async def _run():
        monkeypatch.setattr(telegram_bot, "ALLOWED_USER_IDS", {12345})
        # 1000 '<' chars is <= 3500 raw, but 4000 chars once escaped to '&lt;'
        monkeypatch.setattr(telegram_bot.runner, "get_session_log_export", lambda *a, **kw: "<" * 1000)

        upd = _make_update(user_id=12345)
        await telegram_bot.cmd_logs(upd, _make_context(["conv-123"]))
        assert upd.message.reply_document.await_count == 1
        assert upd.message.reply_text.await_count == 0

    asyncio.run(_run())


def test_handle_prompt_ignores_boot_and_reuses_session_on_injection_failure(monkeypatch, tmp_path):
    async def _run():
        monkeypatch.setattr(telegram_bot, "ALLOWED_USER_IDS", {12345})
        monkeypatch.setattr(telegram_bot, "BOT_STATE_FILE", str(tmp_path / "state.json"))
        monkeypatch.setattr(telegram_bot, "find_interactive_agy_pid", lambda **kw: 5555)
        monkeypatch.setattr(telegram_bot, "get_agy_process_conv_id", lambda proc: None)
        monkeypatch.setattr(telegram_bot, "is_agy_process_busy", lambda pid: False)
        monkeypatch.setattr(telegram_bot, "inject_text_to_agy", lambda text, **kw: False)

        autostart_called = []
        monkeypatch.setattr(telegram_bot, "cmd_autostart", lambda u, c: autostart_called.append(True))

        fake_session = MagicMock()
        fake_session.is_active = True
        fake_session.feed = MagicMock()
        fake_session.set_header_info = MagicMock()
        fake_session.complete = AsyncMock()

        fake_mgr = MagicMock()
        fake_mgr.start_session = AsyncMock(return_value=fake_session)
        monkeypatch.setattr(telegram_bot, "stream_manager", fake_mgr)

        fake_res = SimpleNamespace(
            is_cancelled=False,
            error_message=None,
            full_output="Headless output",
            conversation_id="conv-headless-1",
        )
        monkeypatch.setattr(telegram_bot.runner, "execute_prompt", AsyncMock(return_value=fake_res))
        monkeypatch.setattr(telegram_bot.runner, "conversation_id", "conv-headless-1")

        fake_watcher = MagicMock()
        fake_watcher.mark_conv_caught_up = AsyncMock()
        ctx = _make_context()
        ctx.application.bot_data["watcher"] = fake_watcher

        upd = _make_update(user_id=12345, text="boot")
        await telegram_bot.handle_prompt(upd, ctx)

        # 'boot' must be treated as a prompt, NOT toggle autostart
        assert autostart_called == []
        # Should start exactly ONE stream session and reuse it on injection fallback
        assert fake_mgr.start_session.await_count == 1
        assert fake_watcher.mark_conv_caught_up.await_count == 1
        assert fake_session.complete.await_count == 1

    asyncio.run(_run())


def test_workspace_callback_uses_stable_tokens(monkeypatch, tmp_path):
    async def _run():
        monkeypatch.setattr(telegram_bot, "ALLOWED_USER_IDS", {12345})
        monkeypatch.setattr(telegram_bot, "BOT_STATE_FILE", str(tmp_path / "state.json"))
        ws_root = tmp_path / "ws"
        ws_root.mkdir()
        (ws_root / "alpha").mkdir()
        (ws_root / "beta").mkdir()

        from execution.agy_runner import AntigravityRunner
        test_runner = AntigravityRunner(default_workspace=str(ws_root))
        monkeypatch.setattr(telegram_bot, "runner", test_runner)

        _, markup = telegram_bot.build_workspace_view(test_runner)
        beta_cb = None
        for row in markup.inline_keyboard:
            for btn in row:
                if "beta" in btn.text:
                    beta_cb = btn.callback_data
        assert beta_cb is not None and beta_cb.startswith("ws:sub:")

        # Simulate a new folder appearing alphabetically before beta after keyboard was sent
        (ws_root / "000_inserted").mkdir()

        upd = _make_update(user_id=12345, callback_data=beta_cb)
        await telegram_bot.handle_callback_query(upd, _make_context())
        assert test_runner.workspace_dir.endswith("beta")

    asyncio.run(_run())


def test_state_persistence_roundtrip(monkeypatch, tmp_path):
    ws = tmp_path / "proj"
    ws.mkdir()
    brain = tmp_path / "brain"
    conv_dir = brain / "conv-persist-1"
    conv_dir.mkdir(parents=True)

    state_file = tmp_path / "bot_state.json"
    monkeypatch.setattr(telegram_bot, "BOT_STATE_FILE", str(state_file))
    monkeypatch.setattr(telegram_bot.runner, "brain_dir", str(brain))
    telegram_bot.runner.set_workspace(str(ws))
    telegram_bot.runner.set_conversation("conv-persist-1")

    telegram_bot.save_bot_state(sync_enabled=False)

    # Reset in-memory state and restore
    telegram_bot.runner.workspace_dir = str(tmp_path)
    telegram_bot.runner.conversation_id = None
    telegram_bot._desired_sync_enabled = True

    telegram_bot.restore_bot_state()
    assert telegram_bot.runner.workspace_dir == str(ws)
    assert telegram_bot.runner.conversation_id == "conv-persist-1"
    assert telegram_bot._desired_sync_enabled is False


def test_global_error_handler_behavior():
    async def _run():
        from telegram.error import NetworkError

        # Transient NetworkError should NOT spam user message
        upd_net = _make_update(user_id=12345)
        ctx_net = SimpleNamespace(error=NetworkError("httpx.ConnectError: getaddrinfo failed"))
        await telegram_bot.global_error_handler(upd_net, ctx_net)
        assert upd_net.effective_message.reply_text.await_count == 0

        # Real Update handler error should reply with sanitized summary
        upd_err = Update(update_id=1)
        # Use a mock Update instance matching isinstance(update, Update)
        mock_msg = MagicMock()
        mock_msg.reply_text = AsyncMock()
        real_upd = MagicMock(spec=Update)
        real_upd.effective_message = mock_msg
        ctx_err = SimpleNamespace(error=RuntimeError("Secret sk-proj-abcdef1234567890abcdef leaked"))
        await telegram_bot.global_error_handler(real_upd, ctx_err)
        assert mock_msg.reply_text.await_count == 1
        sent_text = mock_msg.reply_text.call_args.args[0]
        assert "sk-proj-" not in sent_text
        assert "[REDACTED_API_KEY]" in sent_text

    asyncio.run(_run())
