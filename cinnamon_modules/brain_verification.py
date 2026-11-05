"""Outcome classification and conservative retry rules."""
from dataclasses import dataclass
from enum import Enum
class OutcomeKind(str,Enum):
 SUCCESS="success"; FAILURE="failure"; TRANSIENT="transient_failure"; UNCERTAIN="uncertain"
@dataclass(frozen=True)
class Outcome:
 kind: OutcomeKind
 reason: str
@dataclass(frozen=True)
class RetryPolicy:
 max_attempts: int=3
def classify_outcome(reason: str, *, definite: bool=False, transient: bool=False, external_mutation: bool=False)->Outcome:
 text=str(reason or "")[:300]
 if external_mutation and not definite:return Outcome(OutcomeKind.UNCERTAIN,text or "external outcome unknown")
 if definite:return Outcome(OutcomeKind.FAILURE,text)
 if transient:return Outcome(OutcomeKind.TRANSIENT,text)
 return Outcome(OutcomeKind.SUCCESS,text or "completed")
def retry_allowed(outcome: Outcome, *, idempotent: bool, attempts: int, policy: RetryPolicy=RetryPolicy())->bool:
 if type(outcome) is not Outcome or type(idempotent) is not bool or type(attempts) is not int:return False
 return outcome.kind==OutcomeKind.TRANSIENT and idempotent and 0<=attempts<policy.max_attempts
