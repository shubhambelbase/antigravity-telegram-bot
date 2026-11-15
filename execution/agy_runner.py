"""Antigravity CLI Subprocess Runner.

Manages execution of agy CLI commands, streaming output,
session persistence, and process termination.
"""

import asyncio
import glob
import json
import logging
import os
import shutil
import string
from dataclasses import dataclass
from datetime import datetime
from typing import AsyncGenerator, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


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
        except Exception:
            pass

    def _save_recent_workspaces(self) -> None:
        path = self._recent_workspaces_file()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self.recent_workspaces[:5], f, indent=2)
        except Exception:
            pass

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

    def set_conversation(self, conv_id: str) -> bool:
        """Sets the active conversation ID directly."""
        clean_id = conv_id.strip()
        conv_path = os.path.join(self.brain_dir, clean_id)
        if os.path.isdir(conv_path):
            self.conversation_id = clean_id
            return True
        # If passed without full UUID, try matching prefix
        matches = [d for d in os.listdir(self.brain_dir) if d.startswith(clean_id)]
        if len(matches) == 1:
            self.conversation_id = matches[0]
            return True
        return False

    def get_recent_conversations(self, limit: int = 5) -> List[ConversationInfo]:
        """Scans the Antigravity brain directory and returns recent conversations."""
        if not os.path.isdir(self.brain_dir):
            return []

        conv_dirs = glob.glob(os.path.join(self.brain_dir, "*"))
        # Sort by modification time descending
        conv_dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)

        results: List[ConversationInfo] = []
        for d in conv_dirs[:limit]:
            conv_id = os.path.basename(d)
            mtime = os.path.getmtime(d)
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

    def get_session_turns(self, conv_id: Optional[str] = None, limit: int = 5) -> List[Dict[str, Any]]:
        """Extracts recent conversation turns (user requests and model responses) for a session."""
        target_id = conv_id or self.conversation_id or self._get_latest_conversation_id()
        if not target_id:
            return []

        path = os.path.join(self.brain_dir, target_id, ".system_generated", "logs", "transcript.jsonl")
        if not os.path.isfile(path):
            return []

        turns = []
        current_turn: Dict[str, Any] = {"user": "", "model": "", "tools_count": 0, "timestamp": ""}

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
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
        """Generates a clean human-readable log export for a session."""
        target_id = conv_id or self.conversation_id or self._get_latest_conversation_id()
        if not target_id:
            return "No active or recorded session found."

        path = os.path.join(self.brain_dir, target_id, ".system_generated", "logs", "transcript.jsonl")
        if not os.path.isfile(path):
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
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                for line in f:
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
                            output_lines.append(f"[{ts}] USER: {clean}\n")
                        elif src == "MODEL" and rtype == "PLANNER_RESPONSE":
                            th = r.get("thinking", "")
                            if th and th.strip():
                                first_th = th.strip().splitlines()[0][:90]
                                output_lines.append(f"[{ts}] ○ Thought: {first_th}")
                            for tc in r.get("tool_calls", []):
                                tname = tc.get("name", "tool")
                                args = tc.get("args", {})
                                arg_keys = list(args.keys()) if isinstance(args, dict) else []
                                output_lines.append(f"[{ts}] ● Tool: {tname}({arg_keys})")
                            if content and content.strip():
                                output_lines.append(f"[{ts}] MODEL: {content.strip()[:200]}...\n")
                    except Exception:
                        pass
        except Exception as e:
            output_lines.append(f"Error reading transcript: {e}")

        return "\n".join(output_lines[-max_lines:])

    def _get_latest_conversation_id(self) -> Optional[str]:
        """Returns the ID of the most recently modified conversation in brain."""
        if not os.path.isdir(self.brain_dir):
            return None
        dirs = glob.glob(os.path.join(self.brain_dir, "*"))
        if not dirs:
            return None
        dirs.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        return os.path.basename(dirs[0])

    async def cancel(self) -> bool:
        """Kills the running agy process immediately."""
        async with self._lock:
            if self.is_running and self.current_process:
                self._cancelled = True
                try:
                    self.current_process.kill()
                    await self.current_process.wait()
                except ProcessLookupError:
                    pass
                self.current_process = None
                return True
            return False

    async def execute_prompt(
        self,
        prompt: str,
        on_chunk: Optional[Callable[[str], asyncio.Future]] = None,
        timeout: int = 600,
    ) -> RunResult:
        """Executes a prompt via agy in autonomous print mode."""
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
            "--dangerously-skip-permissions",
        ]

        if self.conversation_id:
            cmd.extend(["--conversation", self.conversation_id])
        else:
            cmd.append("--continue")

        # Ensure workspace exists
        if not os.path.exists(self.workspace_dir):
            os.makedirs(self.workspace_dir, exist_ok=True)

        full_output_lines = []

        try:
            self.current_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=self.workspace_dir,
                env=os.environ.copy(),
            )

            async def read_stream():
                assert self.current_process and self.current_process.stdout
                while True:
                    line = await self.current_process.stdout.readline()
                    if not line:
                        break
                    decoded = line.decode("utf-8", errors="replace")
                    full_output_lines.append(decoded)
                    if on_chunk:
                        try:
                            res = on_chunk(decoded)
                            if asyncio.iscoroutine(res):
                                await res
                        except Exception:
                            pass

            try:
                await asyncio.wait_for(read_stream(), timeout=timeout)
                await self.current_process.wait()
            except asyncio.TimeoutError:
                if self.current_process:
                    self.current_process.kill()
                    await self.current_process.wait()
                return RunResult(
                    returncode=-1,
                    full_output="".join(full_output_lines),
                    error_message=f"Execution timed out after {timeout} seconds.",
                )

            returncode = self.current_process.returncode if self.current_process else -1

            # Auto-detect conversation ID if not set, so consecutive turns automatically stay in this session
            if not self.conversation_id:
                latest_id = self._get_latest_conversation_id()
                if latest_id:
                    self.conversation_id = latest_id

            err_msg = None
            if returncode != 0 and not self._cancelled:
                err_msg = f"CLI process exited with non-zero exit code {returncode}."

            return RunResult(
                returncode=returncode or 0,
                full_output="".join(full_output_lines),
                is_cancelled=self._cancelled,
                error_message=err_msg,
                conversation_id=self.conversation_id,
            )

        except Exception as e:
            return RunResult(
                returncode=-1,
                full_output="".join(full_output_lines),
                error_message=f"Failed to execute agy process: {e}",
            )
        finally:
            self.current_process = None
