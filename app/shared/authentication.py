from dataclasses import dataclass

import jwt
from django.conf import settings
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header


@dataclass(frozen=True)
class JWTUser:
    """Lightweight authenticated user object backed by JWT claims."""

    id: int | None
    email: str

    @property
    def is_authenticated(self) -> bool:
        return True


class BearerJWTAuthentication(BaseAuthentication):
    """Authenticate requests using Authorization: Bearer <jwt>."""

    def authenticate(self, request):
        auth = get_authorization_header(request).split()
        if not auth or auth[0].lower() != b"bearer":
            return None

        if len(auth) == 1:
            raise exceptions.AuthenticationFailed("Token ausente")
        if len(auth) > 2:
            raise exceptions.AuthenticationFailed("Header Authorization inválido")

        try:
            token = auth[1].decode("utf-8")
        except UnicodeError as exc:
            raise exceptions.AuthenticationFailed("Token inválido") from exc

        try:
            payload = jwt.decode(
                token,
                settings.SECRET_KEY,
                algorithms=[getattr(settings, "JWT_ALGORITHM", "HS256")],
            )
        except jwt.ExpiredSignatureError as exc:
            raise exceptions.AuthenticationFailed("Token expirado") from exc
        except jwt.InvalidTokenError as exc:
            raise exceptions.AuthenticationFailed("Token inválido") from exc

        user = JWTUser(
            id=payload.get("id"),
            email=payload.get("email", ""),
        )
        return user, payload