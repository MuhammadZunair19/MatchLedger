import hashlib
import secrets
from datetime import timedelta, timezone
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, Response
from pwdlib import PasswordHash
from sqlalchemy import select
from sqlalchemy.orm import Session as DBSession
from .db import get_db
from .config import settings
from .models import Session, Membership, User, now

passwords = PasswordHash.recommended()
DUMMY_HASH = passwords.hash(secrets.token_urlsafe(32))
COOKIE = 'matchledger_session'


def digest(token: str):
    return hashlib.sha256(token.encode()).hexdigest()


def issue_session(db, response: Response, user_id, organization_id):
    token = secrets.token_urlsafe(48)
    session = Session(token_hash=digest(token), csrf_token=secrets.token_urlsafe(32), user_id=user_id,
                      organization_id=organization_id, expires_at=now() + timedelta(hours=settings.session_hours))
    db.add(session)
    response.set_cookie(COOKIE, token, httponly=True, secure=settings.cookie_secure, samesite='lax',
                        max_age=settings.session_hours * 3600, path='/')
    return session


@dataclass
class Context:
    user: User
    membership: Membership
    session: Session

    @property
    def org(self):
        return self.membership.organization_id


def current(request: Request, db: DBSession = Depends(get_db)):
    token = request.cookies.get(COOKIE)
    session = db.scalar(select(Session).where(Session.token_hash == digest(token))) if token else None
    expires_at = (session.expires_at if session.expires_at.tzinfo else session.expires_at.replace(tzinfo=timezone.utc)) if session else None
    if not session or expires_at <= now():
        raise HTTPException(401, 'Please sign in')
    membership = db.scalar(select(Membership).where(Membership.user_id == session.user_id,
                                                     Membership.organization_id == session.organization_id))
    if not membership:
        raise HTTPException(401, 'Organization access has been removed')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        csrf = request.headers.get('x-csrf-token', '')
        if not secrets.compare_digest(csrf, session.csrf_token):
            raise HTTPException(403, 'Invalid CSRF token. Reload and try again.')
    return Context(db.get(User, session.user_id), membership, session)


def owner(ctx: Context):
    if ctx.membership.role != 'owner':
        raise HTTPException(403, 'Only an organization owner can manage members')
