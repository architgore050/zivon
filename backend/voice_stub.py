"""Mount stub for the `voice/` package (ADR-0020, EX1-VOICE seam).

When EX1-VOICE's `voice` package is present in the environment, `mount_voice_channel`
delegates directly to `voice.mount_voice(app)` (or `voice.ws_api.mount_voice(app)`).
When running standalone on `feature/core-backend` before EX1 merges, it mounts a
protocol-compliant WebSocket stub at `/v1/voice` and `/voice/ws` enforcing
session_token auth (`4401`), consent gating (`E-CONSENT-REQUIRED`/`E-CONSENT-STALE`),
and WS rate/concurrency limits (`1013` per backend-spec §8.1–§8.3).
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect

from .errors import APIError


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
        rate_limiter = getattr(app.state, "rate_limiter", None)
        client_ip = (
            websocket.client.host
            if websocket.client and websocket.client.host
            else "127.0.0.1"
        )
        if rate_limiter is not None:
            dec = rate_limiter.check_and_increment(client_ip, "ws")
            if not dec.allowed:
                await websocket.close(code=1013)
                return

        session_token = websocket.query_params.get("session_token", "")
        token_validator = getattr(app.state, "verify_session_token", None)
        identity = getattr(app.state, "identity", None)
        active_session_id: str | None = None

        if token_validator is not None and session_token:
            claims = token_validator(session_token)
            if claims is None:
                await websocket.close(code=4401)
                return
            active_session_id = str(claims.get("session_id") or "")
            if rate_limiter is not None and active_session_id:
                if not rate_limiter.try_acquire_ws_slot(active_session_id):
                    await websocket.close(code=1013)
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
                    claims = (
                        token_validator(tok)
                        if (token_validator is not None and tok)
                        else None
                    )
                    if token_validator is not None and claims is None:
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
                    if claims is not None and identity is not None:
                        try:
                            identity.check_consent_gate(
                                str(claims["device_pseudo_id"])
                            )
                        except APIError as exc:
                            await websocket.send_json(
                                {
                                    "v": 1,
                                    "type": "error",
                                    "payload": {
                                        "code": exc.code,
                                        "message_key": exc.message_key,
                                        "retryable": False,
                                    },
                                }
                            )
                            await websocket.close(code=4403)
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
        finally:
            if rate_limiter is not None and active_session_id:
                rate_limiter.release_ws_slot(active_session_id)

    app.add_api_websocket_route("/v1/voice", _voice_ws_stub, name="voice_v1_stub")
    app.add_api_websocket_route("/voice/ws", _voice_ws_stub, name="voice_ws_stub")
    return "stub"
