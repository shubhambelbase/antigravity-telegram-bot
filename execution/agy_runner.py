"""Antigravity CLI Subprocess Runner.

Manages execution of agy CLI commands using structured NDJSON streaming
(--output-format stream-json), session persistence, workspace navigation,
and safe process-tree termination.
"""

import asyncio
import glob
import json
import logging
import os
import re
import shutil
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import psutil

from execution.formatter import sanitize_secrets
from execution.transcript_watcher import format_tool_call

logger = logging.getLogger(__name__)

SAFE_CONV_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
MAX_TAIL_READ_BYTES = 1024 * 1024  # 1 MiB tail cap for large transcripts
MAX_SAFE_OUTPUT_CHARS = 500_000


@dataclass
class RunResult:
    returncode: int
    full_output: str
    is_cancelled: bool = False
    error_message: Optional[str] = None
    conversation_id: Optional[str] = None


@dataclass
class ConversationInfo:
    conv_id: str
    updated_at: str
    preview: str


def _is_within_directory(base_dir: str, target_path: str) -> bool:
    try:
        base_abs = os.path.abspath(base_dir)
        target_abs = os.path.abspath(target_path)
        return os.path.commonpath([base_abs, target_abs]) == base_abs
    except ValueError:
        return False


def _read_tail_lines(path: str, max_bytes: int = MAX_TAIL_READ_BYTES) -> List[str]:
    """Reads transcript lines efficiently, tailing the last max_bytes if the file is huge."""
    size = os.path.getsize(path)
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
            f.readline()  # Discard partial first line at seek boundary
        return f.readlines()


def _kill_process_tree(proc: Optional[asyncio.subprocess.Process]) -> None:
    """Terminates a subprocess and all of its recursive child processes cleanly."""
    if not proc or proc.pid is None:
        return
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    try:
        proc.kill()
    except ProcessLookupError:
        pass


class AntigravityRunner:
    def __init__(self, agy_path: Optional[str] = None, default_workspace: Optional[str] = None):
        self.agy_path = (
            agy_path
            or shutil.which("agy")
            or shutil.which("agy.exe")
            or os.path.expanduser(r"~\AppData\Local\agy\bin\agy.exe")
        )
        self.workspace_dir = os.path.abspath(default_workspace or os.getcwd())
        self.conversation_id: Optional[str] = None
        self.current_process: Optional[asyncio.subprocess.Process] = None
        self._lock = asyncio.Lock()
        self._cancelled = False
        self.brain_dir = os.path.expanduser(r"~/.gemini/antigravity-cli/brain")
        self.recent_workspaces: List[str] = []
        self._load_recent_workspaces()
        self._record_workspace(self.workspace_dir)

    @property
    def is_running(self) -> bool:
        return self.current_process is not None and self.current_process.returncode is None

    def _recent_workspaces_file(self) -> str:
        return os.path.join(os.path.dirname(os.path.dirname(__file__)), ".tmp", "recent_workspaces.json")

    def _load_recent_workspaces(self) -> None:
        path = self._recent_workspaces_file()
        try:
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8") as f:
                    stored = json.load(f)
                    if isinstance(stored, list):
                        valid = [p for p in stored if isinstance(p, str) and os.path.isdir(p)]
                        for p in reversed(valid):
                            norm = os.path.abspath(p)
                            if norm not in self.recent_workspaces:
                                self.recent_workspaces.insert(0, norm)
                        self.recent_workspaces = self.recent_workspaces[:5]
        except Exception as e:
            logger.debug(f"Could not load recent workspaces: {e}")

    def _save_recent_workspaces(self) -> None:
        path = self._recent_workspaces_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            tmp_path = f"{path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self.recent_workspaces[:5], f, indent=2)
            os.replace(tmp_path, path)
        except Exception as e:
            logger.debug(f"Could not save recent workspaces: {e}")

    def _record_workspace(self, path: str) -> None:
        norm = os.path.abspath(path)
        if norm in self.recent_workspaces:
            self.recent_workspaces.remove(norm)
        self.recent_workspaces.insert(0, norm)
        self.recent_workspaces = self.recent_workspaces[:5]
        self._save_recent_workspaces()

    def resolve_path(self, path: str) -> str:
        """Resolves relative or home paths against the active workspace."""
        clean = os.path.expanduser(path.strip().strip('"').strip("'"))
        if not os.path.isabs(clean):
            return os.path.abspath(os.path.join(self.workspace_dir, clean))
        return os.path.abspath(clean)

    def set_workspace(self, path: str) -> bool:
        """Switches the active workspace directory (resolving relative paths)."""
        if not path or not path.strip():
            return False
        target = self.resolve_path(path)
        if os.path.isdir(target):
            self.workspace_dir = target
            self.conversation_id = None  # Fresh session in new workspace
            self._record_workspace(target)
            return True
        return False

    def create_and_set_workspace(self, path: str) -> bool:
        """Creates a directory if missing and switches workspace into it."""
        if not path or not path.strip():
            return False
        target = self.resolve_path(path)
        try:
            os.makedirs(target, exist_ok=True)
            self.workspace_dir = target
            self.conversation_id = None
            self._record_workspace(target)
            return True
        except Exception as e:
            logger.error(f"Failed to create workspace directory {target}: {e}")
            return False

    def get_workspace_subdirs(self, limit: int = 6) -> List[str]:
        """Returns immediate non-hidden child directories in current workspace."""
        try:
            if not os.path.isdir(self.workspace_dir):
                return []
            entries = os.listdir(self.workspace_dir)
            subdirs = [
                e for e in entries
                if os.path.isdir(os.path.join(self.workspace_dir, e))
                and not e.startswith(".")
                and e != "__pycache__"
                and not e.startswith("$")
            ]
            subdirs.sort(key=str.lower)
            return subdirs[:limit]
        except Exception as e:
            logger.debug(f"Failed to list subdirectories: {e}")
            return []

    def get_parent_workspace(self) -> Optional[str]:
        """Returns parent directory if valid and different from current."""
        parent = os.path.dirname(self.workspace_dir)
        if parent and parent != self.workspace_dir and os.path.isdir(parent):
            return parent
        return None

    def get_available_drives(self) -> List[str]:
        """Returns available drive roots on Windows (e.g. ['C:\\', 'E:\\'])."""
        if os.name != "nt":
            return ["/"]
        try:
            import ctypes
            drives = []
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in string.ascii_uppercase:
                if bitmask & 1:
                    drive_path = f"{letter}:\\"
                    if os.path.isdir(drive_path):
                        drives.append(drive_path)
                bitmask >>= 1
            return drives
        except Exception:
            return ["C:\\"]

    def reset_conversation(self):
        """Starts a fresh session by clearing any tied conversation ID."""
        self.conversation_id = None

    def _sync_workspace_for_conv(self, conv_id: str) -> None:
        try:
            from execution.console_injector import get_workspace_for_conversation
            ws = get_workspace_for_conversation(conv_id)
            if ws and os.path.isdir(ws):
                self.workspace_dir = os.path.abspath(ws)
                self._record_workspace(self.workspace_dir)
        except Exception:
            pass

    def set_conversation(self, conv_id: str) -> bool:
        """Sets the active conversation ID directly with strict path traversal prevention."""
        clean_id = conv_id.strip()
        if not SAFE_CONV_ID_RE.match(clean_id):
            return False

        conv_path = os.path.abspath(os.path.join(self.brain_dir, clean_id))
        if not _is_within_directory(self.brain_dir, conv_path):
            return False

        if os.path.isdir(conv_path):
            self.conversation_id = clean_id
            self._sync_workspace_for_conv(clean_id)
            return True

        if os.path.isdir(self.brain_dir):
            matches = [d for d in os.listdir(self.brain_dir) if d.startswith(clean_id) and SAFE_CONV_ID_RE.match(d)]
            if len(matches) == 1:
                match_path = os.path.abspath(os.path.join(self.brain_dir, matches[0]))
                if _is_within_directory(self.brain_dir, match_path) and os.path.isdir(match_path):
                    self.conversation_id = matches[0]
                    self._sync_workspace_for_conv(matches[0])
                    return True
        return False

    def _get_conversation_mtime(self, conv_path: str) -> float:
        """Returns the latest modification time of transcript.jsonl or the conversation directory.

        Essential on Windows/NTFS where writing to nested transcript.jsonl does not update
        the timestamp of the grandparent session directory.
        """
        transcript_path = os.path.join(conv_path, ".system_generated", "logs", "transcript.jsonl")
        if os.path.isfile(transcript_path):
            try:
                return os.path.getmtime(transcript_path)
            except OSError:
                pass
        try:
            return os.path.getmtime(conv_path)
        except OSError:
            return 0.0

    def get_recent_conversations(self, limit: int = 5) -> List[ConversationInfo]:
        """Scans the Antigravity brain directory and returns recent conversations."""
        if not os.path.isdir(self.brain_dir):
            return []

        conv_dirs = [d for d in glob.glob(os.path.join(self.brain_dir, "*")) if os.path.isdir(d)]
        conv_dirs.sort(key=self._get_conversation_mtime, reverse=True)

        results: List[ConversationInfo] = []
        for d in conv_dirs[:limit]:
            conv_id = os.path.basename(d)
            mtime = self._get_conversation_mtime(d)
            dt_str = datetime.fromtimestamp(mtime).strftime("%b %d %I:%M %p")

            preview = "(Empty or new session)"
            transcript_path = os.path.join(d, ".system_generated", "logs", "transcript.jsonl")
            if os.path.isfile(transcript_path):
                try:
                    with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                        line = f.readline()
                        if line:
                            data = json.loads(line)
                            raw = data.get("content", "")
                            if "<USER_REQUEST>" in raw:
                                inner = raw.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                                preview = inner.replace("\n", " ")[:60]
                            else:
                                preview = raw.strip().replace("\n", " ")[:60]
                except Exception:
                    pass

            results.append(ConversationInfo(conv_id=conv_id, updated_at=dt_str, preview=preview))
        return results

    def _resolve_transcript_file(self, conv_id: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        target_id = conv_id or self.conversation_id or self._get_latest_conversation_id()
        if not target_id or not SAFE_CONV_ID_RE.match(target_id):
            return None, None
        path = os.path.abspath(os.path.join(self.brain_dir, target_id, ".system_generated", "logs", "transcript.jsonl"))
        if not _is_within_directory(self.brain_dir, path):
            return None, None
        return target_id, path

    def get_session_turns(self, conv_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Extracts recent conversation turns (user requests and model responses) for a session."""
        _, path = self._resolve_transcript_file(conv_id)
        if not path or not os.path.isfile(path):
            return []

        turns = []
        current_turn: Dict[str, Any] = {"user": "", "model": "", "tools_count": 0, "timestamp": ""}

        try:
            for line in _read_tail_lines(path):
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                    src = record.get("source")
                    rec_type = record.get("type")
                    content = record.get("content", "")
                    ts = record.get("created_at", "")[:19].replace("T", " ")

                    if src == "USER_EXPLICIT" and rec_type == "USER_INPUT":
                        if current_turn["user"]:
                            turns.append(current_turn)
                        clean_u = content
                        if "<USER_REQUEST>" in content:
                            clean_u = content.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                        current_turn = {"user": clean_u, "model": "", "tools_count": 0, "timestamp": ts}
                    elif src == "MODEL" and rec_type == "PLANNER_RESPONSE":
                        tcs = record.get("tool_calls", [])
                        if tcs:
                            current_turn["tools_count"] += len(tcs)
                        if content and content.strip():
                            current_turn["model"] = content.strip()
                except Exception:
                    pass
            if current_turn["user"]:
                turns.append(current_turn)
        except Exception:
            pass

        return turns[-limit:]

    def get_session_log_export(self, conv_id: Optional[str] = None, max_lines: int = 200) -> str:
        """Generates a clean human-readable log export for a session with path traversal guard and secret redaction."""
        target_id, path = self._resolve_transcript_file(conv_id)
        if not target_id:
            return "No active or recorded session found."
        if not path or not os.path.isfile(path):
            return f"Session transcript file not found for: {target_id}"

        output_lines = [
            "=== Antigravity Session Log ===",
            f"Session ID: {target_id}",
            f"Brain Directory: {os.path.join(self.brain_dir, target_id)}",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 35,
            "",
        ]

        try:
            for line in _read_tail_lines(path):
                if not line.strip():
                    continue
                try:
                    r = json.loads(line)
                    src = r.get("source", "")
                    rtype = r.get("type", "")
                    ts = r.get("created_at", "")[:19].replace("T", " ")
                    content = r.get("content", "")

                    if src == "USER_EXPLICIT":
                        clean = content
                        if "<USER_REQUEST>" in content:
                            clean = content.split("<USER_REQUEST>")[1].split("</USER_REQUEST>")[0].strip()
                        clean_sanitized = sanitize_secrets(clean)
                        output_lines.append(f"[{ts}] USER: {clean_sanitized}\n")
                    elif src == "MODEL" and rtype == "PLANNER_RESPONSE":
                        th = r.get("thinking", "")
                        if th and th.strip():
                            first_th = sanitize_secrets(th.strip().splitlines()[0][:90])
                            output_lines.append(f"[{ts}] ○ Thought: {first_th}")
                        for tc in r.get("tool_calls", []):
                            tname = tc.get("name", "tool")
                            args = tc.get("args", {})
                            arg_keys = list(args.keys()) if isinstance(args, dict) else []
                            output_lines.append(f"[{ts}] ● Tool: {tname}({arg_keys})")
                        if content and content.strip():
                            safe_content = sanitize_secrets(content.strip()[:200])
                            output_lines.append(f"[{ts}] MODEL: {safe_content}...\n")
                except Exception:
                    pass
        except Exception as e:
            output_lines.append(f"Error reading transcript: {e}")

        return "\n".join(output_lines[-max_lines:])

    def _get_latest_conversation_id(self) -> Optional[str]:
        """Returns the ID of the most recently modified conversation in brain."""
        if not os.path.isdir(self.brain_dir):
            return None
        dirs = [d for d in glob.glob(os.path.join(self.brain_dir, "*")) if os.path.isdir(d)]
        if not dirs:
            return None
        dirs.sort(key=self._get_conversation_mtime, reverse=True)
        return os.path.basename(dirs[0])

    async def cancel(self) -> bool:
        """Kills the running agy process and its child process tree immediately."""
        async with self._lock:
            if self.is_running and self.current_process:
                self._cancelled = True
                proc = self.current_process
                _kill_process_tree(proc)
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5.0)
                except Exception:
                    pass
                self.current_process = None
                return True
            return False

    async def execute_prompt(
        self,
        prompt: str,
        on_chunk: Optional[Callable[[str], Any]] = None,
        timeout: int = 600,
    ) -> RunResult:
        """Executes a prompt via agy in headless mode using stream-json NDJSON events."""
        if self.is_running:
            return RunResult(
                returncode=-1,
                full_output="",
                error_message="Another command is currently executing. Use /stop first.",
            )

        self._cancelled = False
        cmd = [
            self.agy_path,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
        ]

        skip_perms = os.getenv("AGY_SKIP_PERMISSIONS", "true").strip().lower() not in ("0", "false", "no")
        if skip_perms:
            cmd.append("--dangerously-skip-permissions")
        mode = os.getenv("AGY_MODE", "").strip()
        if mode:
            cmd.extend(["--mode", mode])
        model = os.getenv("AGY_MODEL", "").strip()
        if model:
            cmd.extend(["--model", model])

        if self.conversation_id:
            cmd.extend(["--conversation", self.conversation_id])

        if not os.path.exists(self.workspace_dir):
            os.makedirs(self.workspace_dir, exist_ok=True)

        streamed_deltas: List[str] = []
        plain_fallback_lines: List[str] = []
        stderr_lines: List[str] = []
        seen_tools: Set[Tuple[int, str]] = set()
        result_response: Optional[str] = None
        result_status: Optional[str] = None
        result_error: Optional[str] = None
        finished_reason: Optional[str] = None
        total_chars = 0

        async def _emit(chunk: str) -> None:
            if not on_chunk or not chunk:
                return
            try:
                res = on_chunk(chunk)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                pass

        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.workspace_dir,
                env=os.environ.copy(),
            )

            async def read_stdout() -> None:
                nonlocal result_response, result_status, result_error, finished_reason, total_chars
                assert self.current_process and self.current_process.stdout
                while True:
                    line = await self.current_process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    stripped = decoded.strip()
                    if not stripped:
                        continue

                    try:
                        payload = json.loads(stripped)
                        if not isinstance(payload, dict) or "event" not in payload:
                            raise ValueError("Not a stream-json event")
                    except Exception:
                        # Plain-text fallback (e.g. direct slash report or older CLI)
                        if total_chars < MAX_SAFE_OUTPUT_CHARS:
                            plain_fallback_lines.append(decoded)
                            total_chars += len(decoded)
                        await _emit(decoded)
                        continue

                    ev_type = payload.get("event")
                    if ev_type == "init":
                        cid = payload.get("conversation_id")
                        if cid:
                            self.conversation_id = cid
                        await _emit("● Session initialized\n")
                    elif ev_type == "step_update":
                        su = payload.get("step_update") or {}
                        cid = su.get("conversation_id")
                        if cid and not self.conversation_id:
                            self.conversation_id = cid

                        step_idx = su.get("step_index", -1)
                        state = su.get("state", "")
                        step_type = su.get("step_type", "")

                        if step_type == "tool":
                            tool_info = su.get("tool_info") or {}
                            tname = su.get("tool_name") or tool_info.get("name") or "tool"
                            params = tool_info.get("parameters") or {}
                            key = (step_idx, tname)
                            if key not in seen_tools:
                                seen_tools.add(key)
                                bullet = format_tool_call({"name": tname, "args": params})
                                await _emit(bullet + "\n")
                            if state == "DONE" and tool_info.get("error"):
                                err_obj = tool_info["error"]
                                msg = err_obj.get("message") if isinstance(err_obj, dict) else str(err_obj)
                                await _emit(f"❌ {tname}: {msg}\n")
                        elif step_type == "agent_response":
                            delta = su.get("text_delta", "")
                            if delta:
                                if total_chars < MAX_SAFE_OUTPUT_CHARS:
                                    streamed_deltas.append(delta)
                                    total_chars += len(delta)
                                await _emit(delta)
                        elif su.get("subagent_info"):
                            subs = su["subagent_info"].get("subagents") or []
                            for s in subs:
                                role = s.get("role") or s.get("type_name") or "subagent"
                                await _emit(f"● Subagent: {role}\n")
                    elif ev_type == "result":
                        res_obj = payload.get("result") or {}
                        cid = res_obj.get("conversation_id")
                        if cid:
                            self.conversation_id = cid
                        result_status = res_obj.get("status")
                        result_error = res_obj.get("error")
                        finished_reason = res_obj.get("finished_reason")
                        if "response" in res_obj:
                            result_response = res_obj.get("response")

            async def read_stderr() -> None:
                assert self.current_process and self.current_process.stderr
                while True:
                    line = await self.current_process.stderr.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    if decoded.strip() and len(stderr_lines) < 200:
                        stderr_lines.append(decoded.strip())

            try:
                await asyncio.wait_for(
                    asyncio.gather(read_stdout(), read_stderr()),
                    timeout=timeout,
                )
                await self.current_process.wait()
            except asyncio.TimeoutError:
                _kill_process_tree(self.current_process)
                if self.current_process:
                    try:
                        await self.current_process.wait()
                    except Exception:
                        pass
                partial = result_response or "".join(streamed_deltas) or "".join(plain_fallback_lines)
                return RunResult(
                    returncode=-1,
                    full_output=partial,
                    error_message=f"Execution timed out after {timeout} seconds.",
                    conversation_id=self.conversation_id,
                )

            returncode = self.current_process.returncode if self.current_process else -1
            final_output = (
                result_response
                if result_response is not None
                else ("".join(streamed_deltas) or "".join(plain_fallback_lines))
            )

            is_cancelled = bool(
                self._cancelled
                or result_status in ("CANCELED", "INTERRUPTED")
                or finished_reason == "interrupted"
            )

            err_msg = None
            if not is_cancelled:
                if result_status in ("ERROR", "INVALID") or result_error:
                    err_msg = result_error or f"Agent run ended with status {result_status}."
                elif finished_reason == "print_timeout":
                    err_msg = "Execution stopped early due to CLI print timeout."
                elif returncode != 0:
                    stderr_tail = "\n".join(stderr_lines[-5:])
                    err_msg = f"CLI process exited with non-zero exit code {returncode}."
                    if stderr_tail:
                        err_msg += f"\n{stderr_tail}"

            return RunResult(
                returncode=returncode if returncode is not None else -1,
                full_output=final_output,
                is_cancelled=is_cancelled,
                error_message=err_msg,
                conversation_id=self.conversation_id,
            )

        except Exception as e:
            partial = result_response or "".join(streamed_deltas) or "".join(plain_fallback_lines)
            return RunResult(
                returncode=-1,
                full_output=partial,
                error_message=f"Failed to execute agy process: {e}",
                conversation_id=self.conversation_id,
            )
        finally:
            self.current_process = None
