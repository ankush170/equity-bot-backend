from mongoengine import connect
import os
from dotenv import load_dotenv
from app.models.models import User
from app.api.v1.services.auth_utils import get_password_hash

# Load environment variables
load_dotenv()

# Connect to MongoDB
connect(db=os.getenv("MONGO_DB"), host=os.getenv("MONGO_URI"))

def fix_user_passwords():
    users = User.objects()
    for user in users:
        # Assuming the current password is in plain text
        plain_password = user.password
        # Hash the password
        hashed_password = get_password_hash(plain_password)
        # Update the user
        user.password = hashed_password
        user.save()
        print(f"Updated password for user: {user.email}")

if __name__ == "__main__":
    fix_user_passwords()
