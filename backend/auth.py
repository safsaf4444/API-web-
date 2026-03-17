from __future__ import annotations

import os
import httpx
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from jose import JWTError, jwt
from passlib.context import CryptContext

# --- CONFIG & CONSTANTS ---
SECRET_KEY = os.getenv("SECRET_KEY") or "dev-secret-change-me"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = int(os.getenv("ACCESS_TOKEN_EXPIRE_HOURS") or "24")

# Google OAuth Config (Ensure these match your Vercel/Google Console settings)
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI")

# Define the router
router = APIRouter(prefix="/auth", tags=["auth"])

# Password hashing context (PBKDF2)
pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

# --- PASSWORD LOGIC ---
def hash_password(password: str) -> str:
    password = (password or "").strip()
    if not password:
        raise HTTPException(status_code=400, detail="Password required.")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters.")
    return pwd_context.hash(password)

def verify_password(password: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(password or "", hashed or "")
    except Exception:
        return False

# --- TOKEN LOGIC ---
def create_access_token(subject: str) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    payload = {"sub": subject, "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def decode_token(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        sub = payload.get("sub")
        if not sub:
            raise HTTPException(status_code=401, detail="Invalid token (missing sub)")
        return str(sub)
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

# --- GOOGLE OAUTH ROUTES ---

@router.get("/google/login")
async def google_login():
    """Step 1: Redirect user to Google"""
    if not GOOGLE_CLIENT_ID or not GOOGLE_REDIRECT_URI:
        raise HTTPException(status_code=400, detail="Google OAuth is not configured in environment variables.")
    
    # Constructing the URL explicitly to avoid mismatch errors
    url = (
        f"https://accounts.google.com/o/oauth2/v2/auth?response_type=code"
        f"&client_id={GOOGLE_CLIENT_ID}"
        f"&redirect_uri={GOOGLE_REDIRECT_URI}"
        f"&scope=openid%20email%20profile"
        f"&access_type=offline"
    )
    return RedirectResponse(url)

@router.get("/google/callback")
async def google_callback(code: str = None):
    """Step 2: Google redirects back here with a code"""
    if not code:
        raise HTTPException(status_code=400, detail="No authorization code received from Google.")

    # 1. Exchange 'code' for 'access_token'
    token_url = "https://oauth2.googleapis.com/token"
    data = {
        "code": code,
        "client_id": GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "grant_type": "authorization_code",
    }

    async with httpx.AsyncClient() as client:
        resp = await client.post(token_url, data=data)
        if resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Google token exchange failed: {resp.text}")
        tokens = resp.json()

    # 2. Use access_token to get user info
    user_info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
    async with httpx.AsyncClient() as client:
        user_resp = await client.get(
            user_info_url, 
            headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        user_data = user_resp.json()

    email = user_data.get("email")
    if not email:
        raise HTTPException(status_code=400, detail="Google did not return an email address.")

    # 3. Success! Issue a Seren token
    access_token = create_access_token(subject=email)

    # Redirect user to the frontend (adjust '/' if you have a specific dashboard path)
    return RedirectResponse(url=f"/?token={access_token}")