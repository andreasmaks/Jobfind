"""Single-owner WebAuthn: public credentials and short-lived, browser-bound challenges."""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from config import CONFIG, ensure_data_dir
from webauthn import generate_registration_options, generate_authentication_options, verify_registration_response, verify_authentication_response, options_to_json
from webauthn.helpers import bytes_to_base64url, base64url_to_bytes
from webauthn.helpers.structs import AuthenticatorSelectionCriteria, PublicKeyCredentialDescriptor, ResidentKeyRequirement, UserVerificationRequirement

DB = CONFIG['data_path'] / 'auth.sqlite3'
TTL = 300


@contextmanager
def connect():
    db = sqlite3.connect(DB, timeout=5)
    db.row_factory = sqlite3.Row
    try:
        with db:
            yield db
    finally:
        db.close()


def init_db():
    ensure_data_dir()
    with connect() as db:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS passkey_owner (id INTEGER PRIMARY KEY CHECK(id=1), handle BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS passkeys (
                credential_id BLOB PRIMARY KEY, public_key BLOB NOT NULL, sign_count INTEGER NOT NULL,
                name TEXT NOT NULL, created_at REAL NOT NULL, last_used_at REAL, rp_id TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS passkey_challenges (
                token_hash TEXT PRIMARY KEY, challenge BLOB NOT NULL, purpose TEXT NOT NULL,
                binding TEXT NOT NULL, origin TEXT NOT NULL, name TEXT NOT NULL, expires_at REAL NOT NULL);
        ''')
        columns = {row[1] for row in db.execute('PRAGMA table_info(sessions)')}
        if 'passkey_id' not in columns:
            db.execute('ALTER TABLE sessions ADD COLUMN passkey_id BLOB')
        db.execute('INSERT OR IGNORE INTO passkey_owner(id,handle) VALUES(1,?)', (secrets.token_bytes(32),))
    DB.chmod(0o600)


def relying_party(origin):
    public = CONFIG['server']['public_origin']
    parsed = urlsplit(origin)
    if public:
        if origin != public or parsed.scheme != 'https':
            raise ValueError('invalid_origin')
    elif origin not in {f"http://localhost:{CONFIG['server']['port']}", f"http://127.0.0.1:{CONFIG['server']['port']}"}:
        raise ValueError('invalid_origin')
    return parsed.hostname


def digest(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


def list_keys(origin):
    rp_id = relying_party(origin)
    with connect() as db:
        return [dict(id=bytes_to_base64url(row['credential_id']), name=row['name'], created_at=row['created_at'], last_used_at=row['last_used_at'])
                for row in db.execute('SELECT * FROM passkeys WHERE rp_id=? ORDER BY created_at', (rp_id,))]


def begin(purpose, origin, session='', name='Passkey'):
    rp_id = relying_party(origin)
    if not isinstance(name, str):
        raise ValueError('invalid_request')
    name = name.strip()
    if purpose not in {'register','auth'} or not 1 <= len(name) <= 80 or any(ord(char)<32 for char in name):
        raise ValueError('invalid_request')
    token = secrets.token_urlsafe(32)
    challenge = secrets.token_bytes(32)
    with connect() as db:
        db.execute('DELETE FROM passkey_challenges WHERE expires_at<=?', (time.time(),))
        if db.execute('SELECT COUNT(*) FROM passkey_challenges').fetchone()[0] >= 100:
            raise ValueError('too_many_requests')
        owner = db.execute('SELECT handle FROM passkey_owner WHERE id=1').fetchone()[0]
        keys = [row[0] for row in db.execute('SELECT credential_id FROM passkeys WHERE rp_id=?', (rp_id,))]
        if purpose == 'register':
            if not session or len(keys)>=20:
                raise ValueError('registration_unavailable')
            options = generate_registration_options(rp_id=rp_id, rp_name='Jobfind', user_name='Jobfind', user_display_name='Jobfind',
                user_id=owner, challenge=challenge, timeout=120000,
                exclude_credentials=[PublicKeyCredentialDescriptor(id=key) for key in keys],
                authenticator_selection=AuthenticatorSelectionCriteria(resident_key=ResidentKeyRequirement.REQUIRED,
                    require_resident_key=True, user_verification=UserVerificationRequirement.REQUIRED))
        else:
            if not keys:
                raise ValueError('no_passkeys')
            options = generate_authentication_options(rp_id=rp_id, challenge=challenge, timeout=120000,
                user_verification=UserVerificationRequirement.REQUIRED)
        db.execute('INSERT INTO passkey_challenges VALUES(?,?,?,?,?,?,?)',
            (digest(token),challenge,purpose,digest(session),origin,name,time.time()+TTL))
    return token, json.loads(options_to_json(options))


def consume(token, purpose, origin, session):
    if not isinstance(token,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',token):
        raise ValueError('invalid_challenge')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row = db.execute('SELECT * FROM passkey_challenges WHERE token_hash=?', (digest(token),)).fetchone()
        db.execute('DELETE FROM passkey_challenges WHERE token_hash=?', (digest(token),))
    if not row or row['expires_at']<=time.time() or row['purpose']!=purpose or row['origin']!=origin or not hmac.compare_digest(row['binding'],digest(session)):
        raise ValueError('invalid_challenge')
    return row


def finish(token, purpose, origin, credential, session='', session_lifetime=30*86400):
    rp_id = relying_party(origin)
    ceremony = consume(token,purpose,origin,session)
    try:
        if not isinstance(credential,dict) or not isinstance(credential.get('response'),dict):
            raise ValueError('invalid_credential')
        client = json.loads(base64url_to_bytes(credential['response']['clientDataJSON']))
        if client.get('crossOrigin',False) is not False or 'topOrigin' in client:
            raise ValueError('cross_origin_not_allowed')
        if purpose=='register':
            verified = verify_registration_response(credential=credential,expected_challenge=ceremony['challenge'],
                expected_rp_id=rp_id,expected_origin=origin,require_user_verification=True,require_user_presence=True)
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if not db.execute('SELECT 1 FROM sessions WHERE token_hash=? AND expires_at>?', (digest(session),time.time())).fetchone():
                    raise ValueError('registration_session_expired')
                if db.execute('SELECT COUNT(*) FROM passkeys').fetchone()[0]>=20:
                    raise ValueError('too_many_passkeys')
                db.execute('INSERT INTO passkeys VALUES(?,?,?,?,?,?,?)',
                    (verified.credential_id,verified.credential_public_key,verified.sign_count,ceremony['name'],time.time(),None,rp_id))
        else:
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                key=db.execute('SELECT * FROM passkeys WHERE credential_id=? AND rp_id=?',
                    (base64url_to_bytes(credential['id']),rp_id)).fetchone()
                owner=db.execute('SELECT handle FROM passkey_owner WHERE id=1').fetchone()[0]
                handle=credential['response'].get('userHandle')
                if not key or not isinstance(handle,str) or not hmac.compare_digest(base64url_to_bytes(handle),owner):
                    raise ValueError('unknown_credential')
                verified=verify_authentication_response(credential=credential,expected_challenge=ceremony['challenge'],
                    expected_rp_id=rp_id,expected_origin=origin,credential_public_key=key['public_key'],
                    credential_current_sign_count=key['sign_count'],require_user_verification=True)
                db.execute('UPDATE passkeys SET sign_count=?,last_used_at=? WHERE credential_id=?',
                    (verified.new_sign_count,time.time(),verified.credential_id))
                # Create the session in the same transaction: a concurrent reset/revocation
                # must not allow a new session after the credential has been removed.
                login_session = secrets.token_urlsafe(32)
                db.execute('DELETE FROM sessions WHERE expires_at<=?', (time.time(),))
                db.execute('INSERT INTO sessions(token_hash,expires_at,passkey_id) VALUES(?,?,?)',
                    (digest(login_session),time.time()+session_lifetime,verified.credential_id))
            return login_session
    except Exception as exc:
        raise ValueError('verification_failed') from exc


def remove(identifier, origin):
    rp_id = relying_party(origin)
    try:
        identifier=base64url_to_bytes(identifier)
    except Exception as exc:
        raise ValueError('invalid_credential') from exc
    with connect() as db:
        if db.execute('DELETE FROM passkeys WHERE credential_id=? AND rp_id=?',(identifier,rp_id)).rowcount != 1:
            raise ValueError('unknown_credential')
        db.execute('DELETE FROM sessions WHERE passkey_id=?', (identifier,))
