import pytest
import sqlite3
import tempfile
import os
from leadforge.execution_state import EntityStateMachine, InvalidTransitionError
from leadforge.validator import validate_transition


def test_business_legal_transitions():
    """Verify legal transitions for Business state machine."""
    assert EntityStateMachine.validate_transition("Business", "DISCOVERED", "QUALIFIED")
    assert EntityStateMachine.validate_transition("Business", "DISCOVERED", "DISQUALIFIED")
    assert EntityStateMachine.validate_transition("Business", "DISCOVERED", "ARCHIVED")
    assert EntityStateMachine.validate_transition("Business", "QUALIFIED", "ARCHIVED")
    assert EntityStateMachine.validate_transition("Business", "DISQUALIFIED", "ARCHIVED")


def test_business_illegal_and_terminal_transitions():
    """Verify illegal and terminal state transitions for Business."""
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Business", "ARCHIVED", "QUALIFIED")
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Business", "QUALIFIED", "DISCOVERED")


def test_opportunity_legal_transitions():
    """Verify legal transitions for Opportunity state machine."""
    assert EntityStateMachine.validate_transition("Opportunity", "PROSPECTING", "QUALIFICATION")
    assert EntityStateMachine.validate_transition("Opportunity", "QUALIFICATION", "PROPOSAL_SENT")
    assert EntityStateMachine.validate_transition("Opportunity", "PROPOSAL_SENT", "NEGOTIATION")
    assert EntityStateMachine.validate_transition("Opportunity", "NEGOTIATION", "CLOSED_WON")
    assert EntityStateMachine.validate_transition("Opportunity", "PROPOSAL_SENT", "CLOSED_LOST")


def test_opportunity_illegal_and_terminal_transitions():
    """Verify illegal and terminal state transitions for Opportunity."""
    # Bypassing intermediate stage
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Opportunity", "PROSPECTING", "CLOSED_WON")
    # Transition from terminal CLOSED_WON
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Opportunity", "CLOSED_WON", "QUALIFICATION")
    # Transition from terminal CLOSED_LOST
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Opportunity", "CLOSED_LOST", "NEGOTIATION")


def test_email_draft_legal_transitions():
    """Verify legal transitions for EmailDraft state machine."""
    assert EntityStateMachine.validate_transition("EmailDraft", "PENDING_APPROVAL", "APPROVED")
    assert EntityStateMachine.validate_transition("EmailDraft", "PENDING_APPROVAL", "REJECTED")
    assert EntityStateMachine.validate_transition("EmailDraft", "APPROVED", "SENT")
    assert EntityStateMachine.validate_transition("EmailDraft", "APPROVED", "FAILED")
    assert EntityStateMachine.validate_transition("EmailDraft", "FAILED", "APPROVED")


def test_email_draft_illegal_and_terminal_transitions():
    """Verify illegal and terminal state transitions for EmailDraft."""
    # Direct send without approval
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("EmailDraft", "PENDING_APPROVAL", "SENT")
    # Terminal SENT cannot transition
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("EmailDraft", "SENT", "PENDING_APPROVAL")
    # Terminal REJECTED cannot transition
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("EmailDraft", "REJECTED", "APPROVED")


def test_lead_legal_transitions():
    """Verify legal transitions for Lead state machine."""
    assert EntityStateMachine.validate_transition("Lead", "OPEN", "CONTACTED")
    assert EntityStateMachine.validate_transition("Lead", "CONTACTED", "QUALIFIED")
    assert EntityStateMachine.validate_transition("Lead", "CONTACTED", "LOST")


def test_lead_illegal_and_terminal_transitions():
    """Verify illegal and terminal state transitions for Lead."""
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Lead", "OPEN", "QUALIFIED")
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("Lead", "LOST", "OPEN")


def test_idempotent_same_state_transition():
    """Verify transitioning to the same state is idempotent (returns True)."""
    assert EntityStateMachine.validate_transition("EmailDraft", "PENDING_APPROVAL", "PENDING_APPROVAL")
    assert EntityStateMachine.validate_transition("Opportunity", "PROSPECTING", "PROSPECTING")


def test_unknown_entity_or_state():
    """Verify unknown entity types or unrecognized initial states raise InvalidTransitionError."""
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("NonExistentEntity", "OPEN", "CLOSED")
    with pytest.raises(InvalidTransitionError):
        EntityStateMachine.validate_transition("EmailDraft", "UNKNOWN_STATUS", "APPROVED")


def test_validator_wrapper_integration():
    """Verify validator module validate_transition wrapper delegates correctly."""
    assert validate_transition("EmailDraft", "PENDING_APPROVAL", "APPROVED")
    with pytest.raises(InvalidTransitionError):
        validate_transition("EmailDraft", "SENT", "PENDING_APPROVAL")
