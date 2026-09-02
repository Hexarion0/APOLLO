import pytest
from apollo.auth import SingleOwnerAuthGuard

def test_single_owner_auth_authorized():
    guard = SingleOwnerAuthGuard(owner_id=123456789)
    assert guard.is_authorized(123456789) is True
    assert guard.is_authorized("123456789") is True

def test_single_owner_auth_unauthorized():
    guard = SingleOwnerAuthGuard(owner_id=123456789)
    assert guard.is_authorized(999999999) is False
    assert guard.is_authorized("unauthorized_user") is False

def test_single_owner_auth_validate_or_raise():
    guard = SingleOwnerAuthGuard(owner_id=123456789)
    guard.validate_or_raise(123456789)  # Should not raise exception

    with pytest.raises(PermissionError):
        guard.validate_or_raise(999999999)

def test_zero_or_empty_owner_id_rejects():
    guard = SingleOwnerAuthGuard(owner_id=0)
    assert guard.is_authorized(0) is False
    assert guard.is_authorized(123456789) is False
