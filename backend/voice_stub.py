"""Mount stub for the `voice/` package (ADR-0020, EX1-VOICE seam).

When EX1-VOICE's `voice` package is present in the environment, `mount_voice_channel`
delegates directly to `voice.mount_voice(app)` (or `voice.ws_api.mount_voice(app)`).
When running standalone on `feature/core-backend` before EX1 merges, it mounts a
minimal protocol-compliant WebSocket stub at `/v1/voice` and `/voice/ws` so
the monolith boots cleanly and health/smoke checks verify the mount seam.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


def mount_voice_channel(app: FastAPI) -> str:
    """Mount the real `voice/` router if available, else mount the EX0 stub."""
    try:
        from voice import mount_voice  # type: ignore[import-not-found]

        mount_voice(app)
        return "voice"
    except ImportError:
        pass

    try:
        from voice.ws_api import mount_voice as mount_ws  # type: ignore[import-not-found]

        mount_ws(app)
        return "voice.ws_api"
    except ImportError:
        pass

    async def _voice_ws_stub(websocket: WebSocket) -> None:
        session_token = websocket.query_params.get("session_token", "")
        token_validator = getattr(app.state, "verify_session_token", None)
        if token_validator is not None and session_token:
            claims = token_validator(session_token)
            if claims is None:
                await websocket.close(code=4401)
                return

        await websocket.accept()
        try:
            while True:
                data: dict[str, Any] = await websocket.receive_json()
                msg_type = data.get("type", "")
                if msg_type == "ping":
                    await websocket.send_json({"v": 1, "type": "pong", "payload": {}})
                elif msg_type == "session.start":
                    tok = data.get("session_token") or session_token
                    if token_validator is not None and (
                        not tok or token_validator(tok) is None
                    ):
                        await websocket.send_json(
                            {
                                "v": 1,
                                "type": "error",
                                "payload": {
                                    "code": "E-UNAUTHORIZED",
                                    "message_key": "error.unauthorized",
                                    "retryable": False,
                                },
                            }
                        )
                        await websocket.close(code=4401)
                        return
                    await websocket.send_json(
                        {
                            "v": 1,
                            "type": "state",
                            "payload": {
                                "state": "voice_enabled",
                                "reason_key": "stub.ready",
                            },
                        }
                    )
                else:
                    await websocket.send_json(
                        {
                            "v": 1,
                            "type": "state",
                            "payload": {
                                "state": "typed_only",
                                "reason_key": "voice.stub_mounted",
                            },
                        }
                    )
        except WebSocketDisconnect:
            return

    app.add_api_websocket_route("/v1/voice", _voice_ws_stub, name="voice_v1_stub")
    app.add_api_websocket_route("/voice/ws", _voice_ws_stub, name="voice_ws_stub")
    return "stub"
