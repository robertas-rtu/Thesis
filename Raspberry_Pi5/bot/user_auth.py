"""User model and authentication management for the Telegram bot."""
import os
import json
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

class UserAuth:
    """Manages user authentication for the Telegram bot."""
    
    def __init__(self, data_dir: str):
        """Initialize UserAuth manager."""
        self.data_dir = data_dir
        self.users_file = os.path.join(data_dir, "bot", "trusted_users.json")
        self.trusted_users: List[int] = []
        self.adding_user_mode: bool = False
        self.adding_user_initiator: Optional[int] = None
        
        os.makedirs(os.path.dirname(self.users_file), exist_ok=True)
        self.load_users()
    
    def load_users(self) -> None:
        """Load trusted users from file."""
        try:
            if os.path.exists(self.users_file):
                with open(self.users_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.trusted_users = data.get("trusted_users", [])
                    logger.info(f"Loaded {len(self.trusted_users)} trusted users from {self.users_file}")
            else:
                logger.info(f"Trusted users file not found at {self.users_file}. Starting with an empty list.")
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding JSON from {self.users_file}: {e}")
        except Exception as e:
            logger.error(f"Error loading trusted users from {self.users_file}: {e}", exc_info=True)
    
    def save_users(self) -> None:
        """Save trusted users to file."""
        try:
            with open(self.users_file, 'w', encoding='utf-8') as f:
                json.dump({"trusted_users": self.trusted_users}, f, indent=2)
            logger.info(f"Saved {len(self.trusted_users)} trusted users to {self.users_file}")
        except Exception as e:
            logger.error(f"Error saving trusted users to {self.users_file}: {e}", exc_info=True)
    
    def is_trusted(self, user_id: int) -> bool:
        """Check if user is trusted."""
        return user_id in self.trusted_users
    
    def add_trusted_user(self, user_id: int) -> bool:
        """Add user to trusted list."""
        if user_id in self.trusted_users:
            logger.warning(f"Attempted to add user {user_id} who is already trusted.")
            return False
            
        self.trusted_users.append(user_id)
        self.save_users()
        logger.info(f"User {user_id} added to trusted users.")
        return True
    
    def start_adding_user(self, initiator_id: int) -> None:
        """Start adding user mode."""
        self.adding_user_mode = True
        self.adding_user_initiator = initiator_id
        logger.info(f"User {initiator_id} activated 'adding new user' mode.")
    
    def stop_adding_user(self) -> None:
        """Stop adding user mode."""
        self.adding_user_mode = False
        self.adding_user_initiator = None
        logger.info("'Adding new user' mode deactivated.")
    
    def is_adding_user_mode(self) -> bool:
        """Check if in adding user mode."""
        return self.adding_user_mode
    
    def process_first_user_if_needed(self, user_id: int) -> bool:
        """Add first user as trusted if no users exist."""
        if not self.trusted_users:
            logger.info(f"No trusted users found. Adding user {user_id} as the first trusted user.")
            self.add_trusted_user(user_id)
            return True
        return False
