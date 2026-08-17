"""LeadForge Communication Engine Package.

Provides multi-turn communication thread tracking, local LLM email copy generation,
IMAP inbox monitoring, zero-shot reply classification, and follow-up sequencing.
"""

from leadforge.communication.base import (
    CommunicationThread,
    CommunicationMessage,
    FollowupSchedule,
)
from leadforge.communication.repository import SQLiteCommunicationRepository

__all__ = [
    "CommunicationThread",
    "CommunicationMessage",
    "FollowupSchedule",
    "SQLiteCommunicationRepository",
]
