from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class QuotaPolicy:
    included_messages: int
    hard_token_cap: int


@dataclass
class QuotaCounter:
    messages_used: int = 0
    tokens_used: int = 0


def allow_request(policy: QuotaPolicy, counter: QuotaCounter, estimated_tokens: int) -> bool:
    if counter.messages_used + 1 > policy.included_messages:
        return False
    if counter.tokens_used + max(estimated_tokens, 0) > policy.hard_token_cap:
        return False
    return True
