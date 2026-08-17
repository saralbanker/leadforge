"""Base classes and value objects for the LeadForge Communication Engine."""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class CommunicationThread:
    """Represents a multi-turn communication thread associated with a business."""

    id: str
    business_id: str
    campaign_name: str
    current_state: str = "PLANNED"
    opportunity_id: Optional[str] = None
    last_activity_at: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass(frozen=True)
class CommunicationMessage:
    """Represents an individual inbound or outbound message within a thread."""

    id: str
    thread_id: str
    direction: str  # OUTBOUND or INBOUND
    sender_email: str
    recipient_email: str
    subject: str
    body_text: str
    message_id_header: Optional[str] = None
    classification_label: Optional[str] = None  # POSITIVE, NEGATIVE, NEUTRAL, UNSUBSCRIBE, BOUNCE, OUT_OF_OFFICE
    prompt_version: Optional[str] = None
    created_at: Optional[str] = None


@dataclass(frozen=True)
class FollowupSchedule:
    """Represents a scheduled follow-up step for an active communication thread."""

    id: str
    thread_id: str
    sequence_step: int
    scheduled_for: str
    status: str = "PENDING"  # PENDING, EXECUTED, CANCELLED, SUPPRESSED
    trigger_reason: Optional[str] = None
    created_at: Optional[str] = None
