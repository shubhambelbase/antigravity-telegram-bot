"""Adaptive Progress System with Indeterminate, Activity-Based, and Determinate States.

Implements real-time progress estimation for autonomous agents:
1. Mode A - Indeterminate: Unknown workload when thinking, exploring, or planning (animated spinner, no percentage).
2. Mode B - Activity-based: Estimated progress based on weighted meaningful work units (planning, exploring, editing, testing, fixing, verification).
3. Mode C - Determinate: Measured finite task progress (e.g. 16/20 tests completed = 80%).

Ensures:
- Progress never jumps backwards.
- Progress never reaches 100% before final verification/completion.
- Work weights adapt dynamically when additional work is discovered.
"""

import html
import re
import time
from enum import Enum
from typing import Dict, List, Optional, Tuple


class ProgressMode(str, Enum):
    INDETERMINATE = "indeterminate"
    ACTIVITY_BASED = "activity"
    DETERMINATE = "determinate"


SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]

# Activity weights defined per user specification (Total: 100)
ACTIVITY_WEIGHTS = {
    "planning": 10.0,
    "exploring": 10.0,
    "editing": 30.0,
    "testing": 25.0,
    "fixing": 15.0,
    "verification": 10.0,
}


def render_progress_bar(pct: float, width: int = 15) -> str:
    """Renders a unicode progress bar (e.g. [████████░░░░░░░])."""
    pct = max(0.0, min(100.0, pct))
    filled = int(round(width * (pct / 100.0)))
    filled = max(0, min(width, filled))
    empty = width - filled
    return "█" * filled + "░" * empty


class AdaptiveProgressTracker:
    """Tracks and calculates adaptive agent progress across Indeterminate, Activity-Based, and Determinate states."""

    def __init__(self, operation_title: str = "Working"):
        self.operation_title = operation_title
        self.mode: ProgressMode = ProgressMode.INDETERMINATE
        self.percentage: float = 0.0
        self._spinner_idx: int = 0
        self._is_completed: bool = False

        # Work units completed per category
        self.units: Dict[str, float] = {
            "planning": 0.0,
            "exploring": 0.0,
            "editing": 0.0,
            "testing": 0.0,
            "fixing": 0.0,
            "verification": 0.0,
        }

        # Categories that have been activated in this task
        self.active_categories = {"planning"}

        # Distinct meaningful activities for display (last 5)
        self.activities: List[str] = []

        # Determinate measured state (Mode C)
        self.determinate_current: int = 0
        self.determinate_total: int = 0
        self.determinate_label: str = ""

    def _next_spinner(self) -> str:
        frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
        self._spinner_idx += 1
        return frame

    def _add_activity(self, text: str):
        """Adds a clean distinct activity to the current activity list, stripping any raw markup."""
        clean = re.sub(r"</?(?:code|b|strong|em|pre|a|i)\b[^>]*>", "", text).strip()
        if not clean:
            return
        # Avoid immediate duplicate
        if self.activities and self.activities[-1] == clean:
            return
        self.activities.append(clean)
        # Keep recent activities (up to 3 for compact display)
        if len(self.activities) > 3:
            self.activities = self.activities[-3:]

    def _recalculate(self):
        """Recalculates progress percentage with dynamic weights and monotonic non-decreasing guarantee."""
        if self._is_completed:
            self.percentage = 100.0
            return

        # Calculate raw completed weight
        raw_completed = sum(self.units.values())

        # If we have reached editing/testing/verification, we operate in activity-based mode
        if any(self.units[cat] > 0 for cat in ("editing", "testing", "fixing", "verification")):
            if self.mode != ProgressMode.DETERMINATE:
                self.mode = ProgressMode.ACTIVITY_BASED

        # Calculate estimated percentage
        new_pct = max(0.0, raw_completed)

        # Monotonic non-decreasing: Never jump backwards!
        self.percentage = max(self.percentage, new_pct)

        # Cap rule: Never reach 100% before final verification/completion
        self.percentage = min(95.0, self.percentage)

    def record_thinking(self, thought_text: str):
        """Records agent thinking/planning (Mode A: Indeterminate)."""
        lines = [line.strip() for line in thought_text.splitlines() if line.strip()]
        if lines:
            first_line = lines[0]
            if len(first_line) > 60:
                first_line = first_line[:57] + "..."
            self._add_activity(f"Planning: {first_line}")
        else:
            self._add_activity("Planning & analyzing requirements")

        self.units["planning"] = min(ACTIVITY_WEIGHTS["planning"], self.units["planning"] + 5.0)
        self.active_categories.add("planning")
        # If no active edits yet, remain in Indeterminate mode
        if not any(self.units[c] > 0 for c in ("editing", "testing", "verification")):
            self.mode = ProgressMode.INDETERMINATE
        self._recalculate()

    def record_exploring(self, target: str):
        """Records file/codebase exploration (Weight: 10)."""
        self._add_activity(f"Reading project files ({target})")
        self.units["exploring"] = min(ACTIVITY_WEIGHTS["exploring"], self.units["exploring"] + 5.0)
        self.active_categories.add("exploring")
        if not any(self.units[c] > 0 for c in ("editing", "testing", "verification")):
            self.mode = ProgressMode.INDETERMINATE
        self._recalculate()

    def record_editing(self, target: str):
        """Records file editing/writing (Weight: 30, switches to Mode B)."""
        self._add_activity(f"Editing {target}")
        self.units["editing"] = min(ACTIVITY_WEIGHTS["editing"], self.units["editing"] + 15.0)
        self.active_categories.add("editing")
        self.mode = ProgressMode.ACTIVITY_BASED
        self._recalculate()

    def record_testing(self, target: str = "Running tests"):
        """Records test execution (Weight: 25, Mode B or Mode C)."""
        self._add_activity(target)
        self.units["testing"] = min(ACTIVITY_WEIGHTS["testing"], self.units["testing"] + 10.0)
        self.active_categories.add("testing")
        if self.mode != ProgressMode.DETERMINATE:
            self.mode = ProgressMode.ACTIVITY_BASED
        self._recalculate()

    def record_determinate_progress(self, current: int, total: int, label: str):
        """Records exact measured task progress (Mode C: Determinate)."""
        if total <= 0:
            return
        self.determinate_current = current
        self.determinate_total = total
        self.determinate_label = label
        self.mode = ProgressMode.DETERMINATE

        det_ratio = min(1.0, current / float(total))
        self.units["testing"] = ACTIVITY_WEIGHTS["testing"] * det_ratio
        self._add_activity(label)
        self._recalculate()

    def record_fixing(self, issue: str = "Resolving error"):
        """Records error recovery / bug fixing (Weight: 15, adapts weights)."""
        self._add_activity(f"Fixing error: {issue}")
        self.units["fixing"] = min(ACTIVITY_WEIGHTS["fixing"], self.units["fixing"] + 7.5)
        self.active_categories.add("fixing")
        self.mode = ProgressMode.ACTIVITY_BASED
        self._recalculate()

    def record_verification(self, check_name: str = "Final verification"):
        """Records final verification checks (Weight: 10)."""
        self._add_activity(check_name)
        self.units["verification"] = min(ACTIVITY_WEIGHTS["verification"], self.units["verification"] + 10.0)
        self.active_categories.add("verification")
        self.mode = ProgressMode.ACTIVITY_BASED
        self._recalculate()

    def complete(self):
        """Marks task as fully completed (100%)."""
        self._is_completed = True
        self.percentage = 100.0
        self.mode = ProgressMode.ACTIVITY_BASED

    def feed_line(self, line: str):
        """Parses a terminal or activity output line and updates progress states automatically."""
        # Strip HTML tags so patterns match clean text without stripping code constructs like vector<int>
        clean = re.sub(r"</?(?:code|b|strong|em|pre|a|i)\b[^>]*>", "", line).strip()
        if not clean:
            return

        # 1. Thought / Planning
        if clean.startswith("○ Thought:") or clean.startswith("Thought:"):
            th = clean.split("Thought:", 1)[1].strip()
            self.record_thinking(th)
            return

        # 2. File Editing
        if clean.startswith("● Edited:") or clean.startswith("● Created:") or clean.startswith("Edited:"):
            fname = clean.split(":", 1)[1].strip()
            self.record_editing(fname)
            return

        # 3. File Exploring
        if clean.startswith("● Read:") or clean.startswith("Read:") or "read_file" in clean or "search_web" in clean:
            if clean.startswith("● Read:") or clean.startswith("Read:"):
                target = clean.split(":", 1)[1].strip()
            else:
                m = re.search(r"read_file\s*\(([^)]+)\)", clean)
                target = m.group(1) if m else "workspace"
            self.record_exploring(target)
            return

        # 4. Determinate Test Progress (Pytest patterns)
        # e.g. "collected 26 items"
        m_coll = re.search(r"collected\s+(\d+)\s+items", clean)
        if m_coll:
            self.determinate_total = int(m_coll.group(1))
            self.record_testing(f"Running test suite ({self.determinate_total} tests)")
            return

        # e.g. "tests/test_foo.py ... [ 65%]"
        m_pct = re.search(r"\[\s*(\d+)%\s*\]", clean)
        if m_pct:
            pct_val = int(m_pct.group(1))
            total = self.determinate_total if self.determinate_total > 0 else 100
            current = int(round(total * (pct_val / 100.0)))
            self.record_determinate_progress(
                current=current,
                total=total,
                label=f"{current}/{total} tests completed",
            )
            return

        # e.g. "26 passed in 2.1s"
        m_passed = re.search(r"(\d+)\s+passed", clean)
        if m_passed:
            passed_cnt = int(m_passed.group(1))
            total = self.determinate_total if self.determinate_total > 0 else passed_cnt
            self.record_determinate_progress(
                current=passed_cnt,
                total=total,
                label=f"{passed_cnt}/{total} tests passed",
            )
            # Switch back to activity-based after test completion
            self.mode = ProgressMode.ACTIVITY_BASED
            return

        # 5. Commands / Testing / Verification
        if clean.startswith("● Ran:") or clean.startswith("Ran:"):
            cmd = clean.split(":", 1)[1].strip()
            if "pytest" in cmd or "test" in cmd:
                self.record_testing("Running tests")
            elif "git status" in cmd or "git diff" in cmd or "git commit" in cmd:
                self.record_verification("Verifying git status & repository")
            else:
                self.record_testing(f"Executing: {cmd[:40]}")
            return

        # 6. Errors & Exceptions
        if clean.startswith("❌") or "error" in clean.lower() or "exception" in clean.lower():
            if not ("0 errors" in clean.lower() or "no error" in clean.lower()):
                self.record_fixing("Resolving error")

    def render_dashboard(self, operation: Optional[str] = None, status: str = "Working") -> str:
        """Renders the Telegram Adaptive Progress Dashboard in HTML."""
        op_title = operation or self.operation_title
        if len(op_title) > 90:
            op_title = op_title[:87] + "..."

        lines = [
            "⚡ <b>Antigravity — Remote Dashboard</b>",
            f"<b>Current operation:</b> {html.escape(status)}",
            f"<i>{html.escape(op_title)}</i>",
            "",
        ]

        # Mode A: Indeterminate
        if self.mode == ProgressMode.INDETERMINATE and not self._is_completed:
            spinner = self._next_spinner()
            lines.append(f"<b>Activity Status:</b> {spinner} <i>Analyzing & Planning (Unknown workload)</i>")
        # Mode C: Determinate (Measured)
        elif self.mode == ProgressMode.DETERMINATE and not self._is_completed:
            det_pct = (self.determinate_current / self.determinate_total * 100.0) if self.determinate_total > 0 else self.percentage
            bar = render_progress_bar(det_pct, width=15)
            lines.append(f"<b>Measured progress:</b> {html.escape(self.determinate_label)} ({int(round(det_pct))}%)")
            lines.append(f"<code>[{bar}]</code>")
        # Mode B: Activity-Based (Estimated) or Completed
        else:
            pct_int = int(round(self.percentage))
            bar = render_progress_bar(self.percentage, width=15)
            label = "Overall progress" if self._is_completed else "Activity-based estimate"
            lines.append(f"<b>{label}:</b> {pct_int}%")
            lines.append(f"<code>[{bar}]</code>")

        lines.append("")
        lines.append("<b>Current activity:</b>")

        display_acts = self.activities if self.activities else ["Initializing environment and analyzing prompt"]
        for act in display_acts:
            lines.append(f"• {html.escape(act)}")

        if not self._is_completed:
            lines.append("<i>Task count unknown · More work may be discovered</i>")

        return "\n".join(lines)
