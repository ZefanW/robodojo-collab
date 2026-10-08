"""Local Codex JSON-RPC transport; no dependency on the retained pipeline."""
import json
import os
from pathlib import Path
import queue
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone


class RpcTrace:
    """Best-effort correlation metadata; never copy message bodies or secrets."""

    def __init__(self, workspace):
        self._lock = threading.Lock()
        self._stream = (Path(workspace) / "rpc_timeline.jsonl").open("a", buffering=1)
        self._lines = {}
        for name in ("rpc_in.jsonl", "rpc_out.jsonl", "stderr.log"):
            path = Path(workspace) / name
            with path.open("rb") as stream:
                self._lines[name] = sum(1 for _ in stream)
        self._sequence = 0
        self.failed = False

    def record(self, direction, raw_log, raw_offset, message=None):
        # Logging must not change delivery, validation, action ordering or retries.
        try:
            with self._lock:
                if self.failed:
                    return
                self._lines[raw_log] += 1
                self._sequence += 1
                row = dict(schema="robodojo.rpc_trace.v1", sequence=self._sequence,
                    utc=datetime.now(timezone.utc).isoformat(timespec="microseconds"),
                    monotonic_ns=time.monotonic_ns(), direction=direction,
                    raw_log=raw_log, raw_line=self._lines[raw_log], raw_offset=raw_offset)
                if isinstance(message, dict):
                    params = message.get("params")
                    params = params if isinstance(params, dict) else {}
                    item = params.get("item")
                    item = item if isinstance(item, dict) else {}
                    turn = params.get("turn")
                    turn = turn if isinstance(turn, dict) else {}
                    fields = dict(rpc_id=message.get("id"), method=message.get("method"),
                        thread_id=params.get("threadId"), turn_id=params.get("turnId", turn.get("id")),
                        item_id=item.get("id", params.get("itemId")), item_type=item.get("type"),
                        call_id=params.get("callId"), tool_name=params.get("tool"))
                    row.update({k: v for k, v in fields.items()
                                if isinstance(v, (str, int)) and not isinstance(v, bool)})
                    if "error" in message:
                        row["has_rpc_error"] = True
                self._stream.write(json.dumps(row, separators=(",", ":")) + "\n")
        except Exception:
            self.failed = True

    def close(self):
        try:
            with self._lock:
                self._stream.close()
        except Exception:
            pass

class StdioAppServer:
    """Small JSON-RPC transport for a single local Codex app-server process."""

    def __init__(self, argv, workspace, *, popen=subprocess.Popen):
        self.workspace = Path(workspace)
        self._incoming = queue.Queue()
        self._responses = {}
        self._response_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._next_id = 1
        self._closed = False
        self._stdout_closed = threading.Event()
        self._in_log = (self.workspace / "rpc_in.jsonl").open("a", buffering=1)
        self._out_log = (self.workspace / "rpc_out.jsonl").open("a", buffering=1)
        self._stderr_log = (self.workspace / "stderr.log").open("a", buffering=1)
        self._trace = RpcTrace(self.workspace)
        agent_cwd = self.workspace/'agent'
        self.process = popen(argv, cwd=agent_cwd if agent_cwd.is_dir() else self.workspace,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
        if self.process.stdin is None or self.process.stdout is None or self.process.stderr is None:
            raise RuntimeError("Codex app-server stdio pipes are unavailable")
        self._stdout_thread = threading.Thread(target=self._read_stdout, daemon=True)
        self._stderr_thread = threading.Thread(target=self._read_stderr, daemon=True)
        self._stdout_thread.start()
        self._stderr_thread.start()

    def _read_stdout(self):
        try:
            for line in self.process.stdout:
                raw_offset = self._out_log.tell()
                self._out_log.write(line)
                try:
                    message = json.loads(line)
                except json.JSONDecodeError as error:
                    self._trace.record("from_codex", "rpc_out.jsonl", raw_offset)
                    self._incoming.put(RuntimeError(f"Non-JSON Codex app-server output: {error}"))
                    continue
                self._trace.record("from_codex", "rpc_out.jsonl", raw_offset, message)
                identifier = message.get("id")
                if identifier is not None and "method" not in message:
                    with self._response_lock:
                        destination = self._responses.get(identifier)
                    if destination is not None:
                        destination.put(message)
                        continue
                self._incoming.put(message)
        finally:
            self._stdout_closed.set()
            # Startup/config errors close stdout before replying to initialize.
            # Wake outstanding RPCs immediately instead of waiting their full timeout.
            with self._response_lock:
                for destination in self._responses.values():
                    try:
                        destination.put_nowait(dict(error=dict(message='Codex app-server stdout closed; inspect stderr.log')))
                    except queue.Full:
                        pass
            self._incoming.put(EOFError("Codex app-server stdout closed"))

    def _read_stderr(self):
        for line in self.process.stderr:
            raw_offset = self._stderr_log.tell()
            self._stderr_log.write(line)
            self._trace.record("stderr", "stderr.log", raw_offset)

    def _send(self, message):
        if self._closed or self._stdout_closed.is_set() or self.process.poll() is not None:
            raise RuntimeError("Codex app-server is not running")
        line = json.dumps(message, separators=(",", ":")) + "\n"
        with self._write_lock:
            raw_offset = self._in_log.tell()
            self._in_log.write(line)
            self._trace.record("to_codex", "rpc_in.jsonl", raw_offset, message)
            self.process.stdin.write(line)
            self.process.stdin.flush()

    def request(self, method, params, timeout):
        with self._response_lock:
            identifier = self._next_id
            self._next_id += 1
            destination = queue.Queue(maxsize=1)
            self._responses[identifier] = destination
        try:
            self._send({"jsonrpc": "2.0", "id": identifier, "method": method, "params": params})
            try:
                response = destination.get(timeout=timeout)
            except queue.Empty as error:
                raise TimeoutError(f"Timed out waiting for Codex RPC {method}") from error
            if "error" in response:
                raise RuntimeError(f"Codex RPC {method} failed: {response['error']}")
            return response.get("result")
        finally:
            with self._response_lock:
                self._responses.pop(identifier, None)

    def notify(self, method, params):
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def reply(self, identifier, result):
        self._send({"jsonrpc": "2.0", "id": identifier, "result": result})

    def next_message(self, timeout):
        try:
            message = self._incoming.get(timeout=timeout)
        except queue.Empty as error:
            raise TimeoutError("Timed out waiting for a Codex turn event") from error
        if isinstance(message, BaseException):
            raise message
        return message

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
                self.process.wait()
        self._stdout_thread.join(timeout=2)
        self._stderr_thread.join(timeout=2)
        for stream in (self._in_log, self._out_log, self._stderr_log):
            stream.close()
        self._trace.close()
