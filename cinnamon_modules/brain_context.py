"""Context signals for Cinnamon's voluntary activity and conversation tone.

No logs or persisted chat excerpts are created here. Matches are conservative
heuristics that prevent bad comedic interruptions; they do NOT classify blame,
criminality, truthfulness, or whether anyone should be punished.
"""
import re

_SERIOUS = (
    re.compile(r"\b(?:please be serious|not a joke|serious question|i need help|"
               r"need someone to listen|feeling overwhelmed|feeling unsafe|"
               r"being harassed|someone is bullying|i'm being bullied|"
               r"stop fighting|don't fight|argument is getting|"
               r"this is an emergency|i'm scared|i am scared)\b", re.IGNORECASE),
    re.compile(r"\b(?:grief|bereavement|emergency services|panic attack|"
               r"bullying incident|serious conflict|threatening me)\b", re.IGNORECASE),
)


def context_looks_serious(text: str) -> bool:
    """Return a tentative context signal, not a moderation finding."""
    sample = str(text or "")[:550]
    return any(pattern.search(sample) for pattern in _SERIOUS)


def conversation_tone(text: str) -> str:
    return ("gentle, factual and non-teasing because the member may need support"
            if context_looks_serious(text) else
            "playful and witty, but accurate and considerate")
