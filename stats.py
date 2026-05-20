import json
import os
import time
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime

STATS_FILE = "logs/session_stats.json"

# Pricing per million tokens (update if model changes)
COST_PER_INPUT_TOKEN  = 0.20  / 1_000_000  # gpt-5.4-nano
COST_PER_OUTPUT_TOKEN = 1.25  / 1_000_000
SUMMARY_INPUT_TOKEN   = 0.15  / 1_000_000  # gpt-4o-mini
SUMMARY_OUTPUT_TOKEN  = 0.60  / 1_000_000


@dataclass
class CallRecord:
    turn: int
    player_input: str
    success: bool
    failure_type: str | None      # None on success
    retry_succeeded: bool         # True if first parse failed but retry worked
    input_tokens: int
    output_tokens: int
    cost_usd: float
    latency_ms: float
    model: str


@dataclass
class SessionStats:
    session_start: str = field(default_factory=lambda: datetime.now().isoformat())
    calls: list[CallRecord] = field(default_factory=list)
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False)

    # running totals — updated after each call
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    total_calls: int = 0
    failed_calls: int = 0
    retry_successes: int = 0

    def record(self, record: CallRecord):
        with self.lock:
            self.calls.append(record)
            self.total_input_tokens  += record.input_tokens
            self.total_output_tokens += record.output_tokens
            self.total_cost_usd      += record.cost_usd
            self.total_calls         += 1
            if not record.success:
                self.failed_calls += 1
            if record.retry_succeeded:
                self.retry_successes += 1

    def summary(self) -> str:
        with self.lock:
            if self.total_calls == 0:
                return "No LLM calls recorded."
            success_rate = ((self.total_calls - self.failed_calls) / self.total_calls) * 100
            avg_cost = self.total_cost_usd / self.total_calls
            lines = [
                f"Session summary ({self.total_calls} calls)",
                f"  Success rate:    {success_rate:.1f}%",
                f"  Retry successes: {self.retry_successes}",
                f"  Hard failures:   {self.failed_calls}",
                f"  Input tokens:    {self.total_input_tokens:,}",
                f"  Output tokens:   {self.total_output_tokens:,}",
                f"  Total cost:      ${self.total_cost_usd:.4f}",
                f"  Avg cost/call:   ${avg_cost:.5f}",
            ]

            # failure breakdown
            failure_types: dict[str, int] = {}
            for c in self.calls:
                if c.failure_type:
                    failure_types[c.failure_type] = failure_types.get(c.failure_type, 0) + 1
            if failure_types:
                lines.append("  Failure breakdown:")
                for ftype, count in failure_types.items():
                    lines.append(f"    {ftype}: {count}")

            # token trend — compare first half vs second half of session
            if self.total_calls >= 4:
                mid = self.total_calls // 2
                first_half_avg  = sum(c.input_tokens for c in self.calls[:mid])  / mid
                second_half_avg = sum(c.input_tokens for c in self.calls[mid:]) / (self.total_calls - mid)
                delta = ((second_half_avg - first_half_avg) / first_half_avg) * 100
                lines.append(f"  Input token drift: {delta:+.1f}% (first half → second half)")

            return "\n".join(lines)

    def flush(self):
        with self.lock:
            os.makedirs("logs", exist_ok=True)
            # Build a serializable dict without the lock object
            data = {
                "session_start": self.session_start,
                "calls": [asdict(c) for c in self.calls],
                "total_input_tokens": self.total_input_tokens,
                "total_output_tokens": self.total_output_tokens,
                "total_cost_usd": self.total_cost_usd,
                "total_calls": self.total_calls,
                "failed_calls": self.failed_calls,
                "retry_successes": self.retry_successes,
            }
            with open(STATS_FILE, "w") as f:
                json.dump(data, f, indent=2)