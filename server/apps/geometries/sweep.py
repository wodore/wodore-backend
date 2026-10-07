"""Shared rich progress plumbing for management-command sweeps.

The display shows the progress bar (with processed/total counts) on top
and the last ten result lines below it, updating in place. Failures are
also written to *stderr*, which the admin runner surfaces as a separate
stream — a rolling error list that survives command success.
"""

from collections import deque
from contextlib import nullcontext

from rich.console import Group
from rich.live import Live
from rich.markup import escape
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from rich.text import Text

_RECENT_MAXLEN = 10


class _RecentResults:
    """Renderable: the last result lines, styled by outcome."""

    def __init__(self, maxlen: int = _RECENT_MAXLEN) -> None:
        self.lines: deque[tuple[str, bool]] = deque(maxlen=maxlen)

    def add(self, message: str, ok: bool) -> None:
        self.lines.append((message, ok))

    def __rich_console__(self, console, options):
        table = Table.grid(padding=(0, 1))
        for message, ok in self.lines:
            table.add_row(Text(escape(message), style="" if ok else "red"))
        yield table


def run_sweep(
    targets,
    *,
    mode: str,
    verb: str,
    no_progress: bool,
    stdout,
    stderr,
    work,
) -> tuple[int, int]:
    """Run *work* for every target behind a rich progress display.

    ``work(place_type, place, report)`` processes one place and must call
    ``report(message, ok)`` for its result lines (plain text; ``ok``
    styles the rolling list), returning whether the place succeeded.

    The bar shows processed/total counts on top; the last ten result
    lines update below it. Failures always go to *stderr* as well.
    Successes are printed to *stdout* only in ``--no-progress`` mode
    (otherwise the live display carries them).

    Returns ``(succeeded, failed)``.
    """
    succeeded = failed = 0
    recent = _RecentResults()

    def report(message: str, ok: bool) -> None:
        recent.add(message, ok)
        if not ok:
            stderr.write(message)
        elif no_progress:
            stdout.write(message)

    progress = Progress(
        SpinnerColumn(finished_text="✓"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TextColumn("•"),
        TimeElapsedColumn(),
        TextColumn("{task.fields[status]}"),
        disable=no_progress,
    )
    with (
        nullcontext()
        if no_progress
        # The default rich console resolves sys.stdout dynamically, so the
        # display lands in the admin runner's captured output stream.
        else Live(Group(progress, recent), refresh_per_second=8)
    ):
        task = progress.add_task(
            f"[cyan]{verb} ({mode})...",
            total=len(targets),
            status="[dim]starting...",
        )
        for place_type, place in targets:
            progress.update(task, status=f"[cyan]{place_type}:{place.slug}")
            if work(place_type, place, report):
                succeeded += 1
            else:
                failed += 1
            progress.advance(task)
    return succeeded, failed
