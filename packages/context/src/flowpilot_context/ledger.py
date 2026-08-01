"""Cross-turn context token accounting (FP-CTX-004).

The single-call ceiling lives on ``ContextPolicy.token_budget`` and is
enforced by ``ContextEnvelope`` at construction time.  This module adds the
missing cross-turn half of the contract: a ``ContextBudgetLedger`` that
charges every model call and keeps the whole conversation under a hard
cumulative token budget.  The ledger is serializable so interrupted or
restarted runs rebuild their counters from a Checkpoint instead of charging
the same turns twice (FP-FLOW-005 / FP-DATA-001 linkage).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .errors import ContextError, ContextErrorCode
from .models import TokenUsageRecord

_BUDGET_CHECKPOINT_SCHEMA = "flowpilot.context-budget-ledger.v1"


@dataclass(frozen=True, slots=True)
class BudgetExhaustion:
    """Why the ledger stopped a conversation (FP-FLOW-006 linkage)."""

    reason_code: str
    detail: str
    round_count: int
    used_total_tokens: int
    cumulative_token_budget: int

    def to_mapping(self) -> dict[str, Any]:
        return {
            "reason_code": self.reason_code,
            "detail": self.detail,
            "round_count": self.round_count,
            "used_total_tokens": self.used_total_tokens,
            "cumulative_token_budget": self.cumulative_token_budget,
        }


class ContextBudgetLedger:
    """Append-only cross-turn token accounting with a hard cumulative cap.

    ``charge`` is the only mutation path.  It either records the call or
    raises ``ContextError(BUDGET_EXHAUSTED)`` without mutating the ledger,
    so a denied call never leaks partial accounting.  Counters are rebuilt
    from a Checkpoint snapshot with ``restore``; ``restore`` is idempotent
    and therefore safe to call before every prepare.
    """

    def __init__(
        self,
        *,
        cumulative_token_budget: int,
        maximum_rounds: int = 50,
    ) -> None:
        if cumulative_token_budget < 1:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "cumulative token budget must be positive",
            )
        if maximum_rounds < 1:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "maximum conversation rounds must be positive",
            )
        self._cumulative_budget = cumulative_token_budget
        self._maximum_rounds = maximum_rounds
        self._entries: list[TokenUsageRecord] = []
        # Checkpoint-restored counters: the authoritative cumulative state
        # carried across a restart.  Entries only cover live (post-restore)
        # turns, so restored usage is never double-counted or lost.
        self._restored_rounds = 0
        self._restored_input = 0
        self._restored_output = 0

    @property
    def cumulative_token_budget(self) -> int:
        return self._cumulative_budget

    @property
    def maximum_rounds(self) -> int:
        return self._maximum_rounds

    @property
    def round_count(self) -> int:
        return self._restored_rounds + len(self._entries)

    @property
    def used_input_tokens(self) -> int:
        return self._restored_input + sum(
            entry.input_tokens for entry in self._entries
        )

    @property
    def used_output_tokens(self) -> int:
        return self._restored_output + sum(
            entry.output_tokens for entry in self._entries
        )

    @property
    def used_total_tokens(self) -> int:
        return sum(entry.total_tokens for entry in self._entries)

    @property
    def remaining_tokens(self) -> int:
        return max(0, self._cumulative_budget - self.used_total_tokens)

    @property
    def entries(self) -> tuple[TokenUsageRecord, ...]:
        return tuple(self._entries)

    @property
    def is_exhausted(self) -> bool:
        """True when a subsequent model call would be denied up front."""
        return (
            self.round_count >= self._maximum_rounds
            or self.used_total_tokens >= self._cumulative_budget
        )

    @property
    def exhaustion(self) -> BudgetExhaustion | None:
        if self.round_count >= self._maximum_rounds:
            return BudgetExhaustion(
                reason_code="maximum_rounds",
                detail=(
                    f"conversation reached the {self._maximum_rounds} round "
                    "hard limit"
                ),
                round_count=self.round_count,
                used_total_tokens=self.used_total_tokens,
                cumulative_token_budget=self._cumulative_budget,
            )
        if self.used_total_tokens >= self._cumulative_budget:
            return BudgetExhaustion(
                reason_code="cumulative_tokens",
                detail=(
                    "conversation reached the hard cumulative token budget "
                    f"({self.used_total_tokens}/{self._cumulative_budget})"
                ),
                round_count=self.round_count,
                used_total_tokens=self.used_total_tokens,
                cumulative_token_budget=self._cumulative_budget,
            )
        return None

    def charge(
        self,
        *,
        turn_index: int,
        request_id: str,
        context_id: str,
        agent_id: str,
        input_tokens: int,
        output_tokens: int,
        layer_tokens: Sequence[tuple[str, int]] = (),
    ) -> TokenUsageRecord:
        if turn_index != self.round_count:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "turn index must match the ledger round count",
            )
        if self.round_count >= self._maximum_rounds:
            raise self._exhausted("maximum_rounds")
        total = input_tokens + output_tokens
        if self.used_total_tokens + total > self._cumulative_budget:
            raise self._exhausted("cumulative_tokens")
        record = TokenUsageRecord(
            turn_index=turn_index,
            request_id=request_id,
            context_id=context_id,
            agent_id=agent_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total,
            layer_tokens=tuple(layer_tokens),
        )
        self._entries.append(record)
        return record

    def restore(
        self,
        *,
        round_count: int,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Rebuild counters from a Checkpoint (idempotent, FP-FLOW-005).

        Only the authoritative cumulative counters are restored so a
        replayed run never double-charges.  A fresh ledger adopts the
        Checkpoint counters wholesale; an already charged ledger only
        accepts an identical snapshot, which makes ``restore`` safe to call
        before every prepare.
        """
        if round_count < 0 or input_tokens < 0 or output_tokens < 0:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "checkpoint budget counters cannot be negative",
            )
        identical = (
            round_count == self.round_count
            and input_tokens == self.used_input_tokens
            and output_tokens == self.used_output_tokens
        )
        if identical:
            return
        if self.round_count != 0 or self._entries:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "checkpoint budget counters do not match the live ledger",
            )
        # Fresh ledger: adopt the Checkpoint counters wholesale.
        self._restored_rounds = round_count
        self._restored_input = input_tokens
        self._restored_output = output_tokens

    def report(self) -> dict[str, Any]:
        """Per-turn and cumulative token distribution with real numbers."""
        return {
            "schema": _BUDGET_CHECKPOINT_SCHEMA + ".report",
            "cumulative_token_budget": self._cumulative_budget,
            "maximum_rounds": self._maximum_rounds,
            "round_count": self.round_count,
            "restored_rounds": self._restored_rounds,
            "restored_input_tokens": self._restored_input,
            "restored_output_tokens": self._restored_output,
            "used_input_tokens": self.used_input_tokens,
            "used_output_tokens": self.used_output_tokens,
            "used_total_tokens": self.used_total_tokens,
            "remaining_tokens": self.remaining_tokens,
            "is_exhausted": self.is_exhausted,
            "turns": [entry.to_mapping() for entry in self._entries],
            "layer_totals": self._layer_totals(),
        }

    def to_checkpoint(self) -> dict[str, Any]:
        return {
            "schema": _BUDGET_CHECKPOINT_SCHEMA,
            "round_count": self.round_count,
            "input_tokens": self.used_input_tokens,
            "output_tokens": self.used_output_tokens,
        }

    @classmethod
    def from_checkpoint(
        cls,
        value: Mapping[str, Any],
        *,
        cumulative_token_budget: int,
        maximum_rounds: int,
    ) -> ContextBudgetLedger:
        ledger = cls(
            cumulative_token_budget=cumulative_token_budget,
            maximum_rounds=maximum_rounds,
        )
        if value.get("schema") != _BUDGET_CHECKPOINT_SCHEMA:
            raise ContextError(
                ContextErrorCode.INVALID_CONTEXT,
                "budget checkpoint does not match the v1 schema",
            )
        ledger.restore(
            round_count=int(value["round_count"]),
            input_tokens=int(value["input_tokens"]),
            output_tokens=int(value["output_tokens"]),
        )
        return ledger

    def _exhausted(self, reason_code: str) -> ContextError:
        exhaustion = BudgetExhaustion(
            reason_code=reason_code,
            detail=(
                f"hard conversation budget reached: {reason_code}"
                + (
                    f" (round {self.round_count}/{self._maximum_rounds})"
                    if reason_code == "maximum_rounds"
                    else f" ({self.used_total_tokens}/{self._cumulative_budget} tokens)"
                )
            ),
            round_count=self.round_count,
            used_total_tokens=self.used_total_tokens,
            cumulative_token_budget=self._cumulative_budget,
        )
        return ContextError(
            ContextErrorCode.BUDGET_EXHAUSTED,
            exhaustion.detail,
        )

    def _layer_totals(self) -> dict[str, int]:
        totals: dict[str, int] = {}
        for entry in self._entries:
            for layer, tokens in entry.layer_tokens:
                totals[layer] = totals.get(layer, 0) + tokens
        return dict(sorted(totals.items()))
