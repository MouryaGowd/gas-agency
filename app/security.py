import hashlib
import hmac
import os
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from . import config

_N, _R, _P = 2**14, 8, 1
_DUMMY = None


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-ish time even when the user does not exist (stored=None)."""
    global _DUMMY
    if stored is None:
        _DUMMY = _DUMMY or hash_password("dummy-password")
        stored = _DUMMY
        password = password + "x"
    try:
        _, salt_hex, digest_hex = stored.split("$")
        digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=_N, r=_R, p=_P)
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


def new_csrf() -> str:
    return secrets.token_urlsafe(24)


def _link_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(config.SECRET_KEY, salt="restock-booking-link")


def make_booking_token(customer_id: int, product_id: int, qty: int) -> str:
    return _link_serializer().dumps({"c": customer_id, "p": product_id, "q": qty})


def read_booking_token(token: str) -> dict | None:
    try:
        return _link_serializer().loads(token, max_age=config.BOOKING_LINK_DAYS * 86400)
    except (BadSignature, SignatureExpired):
        return None
