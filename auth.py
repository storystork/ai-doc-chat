#import re
#from typing import Optional, Tuple
#
#import bcrypt
#
#from database import Database
#
#
#def _normalize_email(email: str) -> str:
#    return email.strip().lower()
#
#
#def hash_password(password: str) -> str:
#    pw = password.encode("utf-8")
#    salt = bcrypt.gensalt(rounds=12)
#    hashed = bcrypt.hashpw(pw, salt)
#    return hashed.decode("utf-8")
#
#
#def verify_password(password: str, password_hash: str) -> bool:
#    pw = password.encode("utf-8")
#    return bcrypt.checkpw(pw, password_hash.encode("utf-8"))
#
#
#def validate_password(password: str) -> Optional[str]:
#    if len(password) < 8:
#        return "Password must be at least 8 characters."
#    if not re.search(r"[A-Za-z]", password):
#        return "Password must include at least one letter."
#    if not re.search(r"[0-9]", password):
#        return "Password must include at least one number."
#    return None
#
#
#def signup(db: Database, email: str, password: str) -> Tuple[bool, str]:
#    email = _normalize_email(email)
#    existing = db.get_user_by_email(email)
#    if existing:
#        return False, "An account with this email already exists."
#    err = validate_password(password)
#    if err:
#        return False, err
#    password_hash = hash_password(password)
#    user_id = db.create_user(email, password_hash)
#    return True, f"Signup successful. User id: {user_id}"
#
#
#def login(db: Database, email: str, password: str):
#    email = _normalize_email(email)
#    user = db.get_user_by_email(email)
#    if not user:
#        return False, None, "Invalid email or password."
#    if not verify_password(password, user["password_hash"]):
#        return False, None, "Invalid email or password."
#    return True, user, "Login successful."
#
#

import os
import re
from typing import Optional, Tuple

import bcrypt
import requests

from database import Database


# ─────────────────────────────────────────────
#  Helpers
# ─────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    return email.strip().lower()


# ─────────────────────────────────────────────
#  Password auth
# ─────────────────────────────────────────────

def hash_password(password: str) -> str:
    pw = password.encode("utf-8")
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(pw, salt)
    return hashed.decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    pw = password.encode("utf-8")
    return bcrypt.checkpw(pw, password_hash.encode("utf-8"))


def validate_password(password: str) -> Optional[str]:
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if not re.search(r"[A-Za-z]", password):
        return "Password must include at least one letter."
    if not re.search(r"[0-9]", password):
        return "Password must include at least one number."
    return None


def signup(db: Database, email: str, password: str) -> Tuple[bool, str]:
    email = _normalize_email(email)
    existing = db.get_user_by_email(email)
    if existing:
        return False, "An account with this email already exists."
    err = validate_password(password)
    if err:
        return False, err
    password_hash = hash_password(password)
    user_id = db.create_user(email, password_hash)
    return True, f"Signup successful. User id: {user_id}"


def login(db: Database, email: str, password: str):
    email = _normalize_email(email)
    user = db.get_user_by_email(email)
    if not user:
        return False, None, "Invalid email or password."
    if not verify_password(password, user["password_hash"]):
        return False, None, "Invalid email or password."
    return True, user, "Login successful."


# ─────────────────────────────────────────────
#  Google OAuth 2.0
# ─────────────────────────────────────────────

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"


def get_google_auth_url(redirect_uri: str) -> str:
    """
    Build the Google OAuth consent-screen URL.

    Required env vars:
        GOOGLE_CLIENT_ID  – from Google Cloud Console
    """
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "offline",
        "prompt": "select_account",
    }
    query = "&".join(f"{k}={requests.utils.quote(str(v))}" for k, v in params.items())
    return f"{GOOGLE_AUTH_URL}?{query}"


def exchange_google_code(code: str, redirect_uri: str) -> dict:
    """
    Exchange an authorization code for tokens, then fetch user info.

    Required env vars:
        GOOGLE_CLIENT_ID
        GOOGLE_CLIENT_SECRET

    Returns a dict with at least: { email, name, google_id, picture }
    Raises ValueError on failure.
    """
    client_id = os.environ["GOOGLE_CLIENT_ID"]
    client_secret = os.environ["GOOGLE_CLIENT_SECRET"]

    # 1. Exchange code for tokens
    token_resp = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=10,
    )
    token_data = token_resp.json()
    if "error" in token_data:
        raise ValueError(f"Token exchange failed: {token_data.get('error_description', token_data['error'])}")

    access_token = token_data["access_token"]

    # 2. Fetch user profile
    userinfo_resp = requests.get(
        GOOGLE_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    userinfo = userinfo_resp.json()
    if "email" not in userinfo:
        raise ValueError("Google did not return an email address.")

    return {
        "email": _normalize_email(userinfo["email"]),
        "name": userinfo.get("name", ""),
        "google_id": userinfo.get("sub", ""),
        "picture": userinfo.get("picture", ""),
        "email_verified": userinfo.get("email_verified", False),
    }


def google_auth_or_signup(db: Database, google_user: dict) -> Tuple[bool, Optional[dict], str]:
    """
    Given verified Google user info, find or create a local account.

    - If a user with this email already exists → log them in (regardless of
      whether they originally signed up with Google or a password).
    - If no user exists → create one with a NULL password_hash (Google-only
      account) and log them in.

    Returns (success, user_row, message).
    """
    email = google_user["email"]
    user = db.get_user_by_email(email)

    if user:
        # Existing account – just return it
        return True, user, "Login successful."

    # New account via Google – no password needed
    user_id = db.create_user(email, password_hash=None)  # type: ignore[arg-type]
    user = db.get_user_by_id(user_id)
    return True, user, f"Account created via Google. Welcome, {google_user.get('name', email)}!"