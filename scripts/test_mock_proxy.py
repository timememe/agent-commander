"""Minimal mock CLIProxyAPI server for testing agent-commander-gui proxy_api mode.

Run:  python test_mock_proxy.py
Then: set proxyApi.enabled=true in config and launch GUI.

Implements /v1/chat/completions with SSE streaming.
"""

import json
import time
from http.server import HTTPServer, BaseHTTPRequestHandler


class MockHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/v1/models":
            self._json_response(200, {
                "data": [
                    {"id": "claude-sonnet-4-5", "object": "model"},
                    {"id": "gemini-2.5-pro", "object": "model"},
                    {"id": "gpt-5-codex", "object": "model"},
                ]
            })
            return
        self._json_response(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/v1/chat/completions":
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}

            model = body.get("model", "unknown")
            messages = body.get("messages", [])
            user_msg = messages[-1]["content"] if messages else "hello"
            stream = body.get("stream", False)

            # Generate a mock response
            response_text = (
                f"Hello from mock proxy! You asked: \"{user_msg[:100]}...\"\n\n"
                f"Model: {model}\n"
                f"This is a test response to verify the agent-commander-gui proxy_api pipeline works.\n\n"
                f"The streaming SSE transport is functioning correctly."
            )

            if stream:
                self._stream_sse(model, response_text)
            else:
                self._json_response(200, {
                    "choices": [{
                        "message": {"role": "assistant", "content": response_text},
                        "finish_reason": "stop",
                    }]
                })
            return

        self._json_response(404, {"error": "not found"})

    def _stream_sse(self, model: str, text: str):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()

        # Stream token-by-token (word-by-word for readability)
        words = text.split(" ")
        for i, word in enumerate(words):
            token = word if i == 0 else f" {word}"
            chunk = {
                "choices": [{
                    "delta": {"content": token},
                    "finish_reason": None,
                }]
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(0.05)  # 50ms per token — visible streaming

        # Send [DONE]
        self.wfile.write(b"data: [DONE]\n\n")
        self.wfile.flush()

    def _json_response(self, code: int, data: dict):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        print(f"[mock-proxy] {args[0]}")


if __name__ == "__main__":
    port = 8317
    server = HTTPServer(("127.0.0.1", port), MockHandler)
    print(f"Mock CLIProxyAPI running on http://127.0.0.1:{port}")
    print(f"Endpoints:")
    print(f"  GET  /v1/models")
    print(f"  POST /v1/chat/completions")
    print(f"\nPress Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
