"""Unit tests for the Adaptive Progress System."""

import pytest
from execution.progress_tracker import (
    AdaptiveProgressTracker,
    ProgressMode,
    render_progress_bar,
)


def test_render_progress_bar():
    assert render_progress_bar(0, width=10) == "░░░░░░░░░░"
    assert render_progress_bar(50, width=10) == "█████░░░░░"
    assert render_progress_bar(100, width=10) == "██████████"


def test_indeterminate_mode():
    tracker = AdaptiveProgressTracker(operation_title="Explore code")
    tracker.record_thinking("Analyzing project architecture and files")
    assert tracker.mode == ProgressMode.INDETERMINATE

    tracker.record_exploring("execution/screenshot.py")
    assert tracker.mode == ProgressMode.INDETERMINATE

    dashboard = tracker.render_dashboard(status="Working")
    assert "Analyzing & Planning" in dashboard
    assert "Activity-based estimate" not in dashboard
    assert "Reading project files" in dashboard
    # Verify indeterminate skeleton loading bar is present
    assert "Loading..." in dashboard
    assert "[" in dashboard and "]" in dashboard


def test_activity_based_mode():
    tracker = AdaptiveProgressTracker(operation_title="Implementing feature")
    tracker.record_thinking("Planning edits")
    tracker.record_editing("execution/telegram_bot.py")

    assert tracker.mode == ProgressMode.ACTIVITY_BASED
    assert tracker.percentage > 0.0

    dashboard = tracker.render_dashboard(status="Working")
    assert "Activity-based estimate" in dashboard
    assert "Editing execution/telegram_bot.py" in dashboard
    assert "[" in dashboard and "]" in dashboard  # Progress bar present


def test_determinate_mode():
    tracker = AdaptiveProgressTracker(operation_title="Running test suite")
    tracker.record_editing("tests/test_suite.py")

    # Mode C: Determinate
    tracker.record_determinate_progress(16, 20, "16/20 tests completed")
    assert tracker.mode == ProgressMode.DETERMINATE
    assert tracker.determinate_current == 16
    assert tracker.determinate_total == 20

    dashboard = tracker.render_dashboard(status="Working")
    assert "Measured progress:" in dashboard
    assert "16/20 tests completed (80%)" in dashboard


def test_monotonic_non_decreasing():
    tracker = AdaptiveProgressTracker(operation_title="Test Monotonicity")
    tracker.record_editing("file1.py")
    pct1 = tracker.percentage
    assert pct1 > 0

    tracker.record_editing("file2.py")
    pct2 = tracker.percentage
    assert pct2 >= pct1

    # Simulate discovering error
    tracker.record_fixing("Handling null pointer")
    pct3 = tracker.percentage
    assert pct3 >= pct2  # Must not jump backwards!

    # Cap rule
    assert tracker.percentage <= 95.0

    # Completion
    tracker.complete()
    assert tracker.percentage == 100.0


def test_feed_line_integration():
    tracker = AdaptiveProgressTracker(operation_title="Full Workflow")
    tracker.feed_line("○ Thought: Examining directory structure")
    assert tracker.mode == ProgressMode.INDETERMINATE

    tracker.feed_line("● Tool: read_file (execution/screenshot.py)")
    assert tracker.mode == ProgressMode.INDETERMINATE

    tracker.feed_line("● Edited: execution/telegram_bot.py")
    assert tracker.mode == ProgressMode.ACTIVITY_BASED

    tracker.feed_line("● Ran: pytest tests/")
    tracker.feed_line("collected 20 items")
    tracker.feed_line("tests/test_foo.py ... [ 80%]")

    assert tracker.mode == ProgressMode.DETERMINATE
    assert tracker.determinate_current == 16
    assert tracker.determinate_total == 20

    tracker.feed_line("20 passed in 1.5s")
    tracker.feed_line("● Ran: git status")
    assert tracker.percentage <= 95.0

    tracker.complete()
    assert tracker.percentage == 100.0


def test_progress_tracker_strips_html_tags():
    tracker = AdaptiveProgressTracker(operation_title="HTML Strip Test")
    tracker.feed_line("○ Thought: <i>Checking configuration settings</i>")
    tracker.feed_line("● Edited: <code>types<int>.ts</code>")
    tracker.feed_line("● Read: <code>test_watcher.py</code>")

    dashboard = tracker.render_dashboard()
    assert "<code>types<int>.ts" not in dashboard
    assert "<code>test_watcher.py" not in dashboard
    assert "<i>Checking" not in dashboard
    assert "• Editing types&lt;int&gt;.ts" in dashboard
    assert "• Reading project files (test_watcher.py)" in dashboard
