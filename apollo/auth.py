import logging
from typing import Optional, Union

logger = logging.getLogger("apollo.auth")

class SingleOwnerAuthGuard:
    """Authentication guard enforcing single-owner identity validation.
    
    Rejects any request or sender whose ID does not match the configured owner.
    """

    def __init__(self, owner_id: Union[int, str]):
        self.owner_id = str(owner_id).strip()

    def is_authorized(self, sender_id: Union[int, str]) -> bool:
        """Check if sender matches owner ID exactly."""
        if not self.owner_id or self.owner_id == "0":
            logger.warning("AuthGuard owner_id is not set or zero! Rejecting all requests.")
            return False
        
        is_owner = str(sender_id).strip() == self.owner_id
        if not is_owner:
            logger.warning(f"Unauthorized access attempt rejected for sender_id={sender_id}")
        return is_owner

    def validate_or_raise(self, sender_id: Union[int, str]) -> None:
        """Validate sender ID and raise PermissionError if unauthorized."""
        if not self.is_authorized(sender_id):
            raise PermissionError(f"Access denied. Sender '{sender_id}' is not the authorized owner.")
