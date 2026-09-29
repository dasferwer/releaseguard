import secrets
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from releaseguard.config import get_settings

bearer = HTTPBearer(auto_error=False)


@dataclass(frozen=True, slots=True)
class Principal:
    name: str
    role: str


def authenticate(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Principal:
    if credentials is not None:
        for name, client in get_settings().api_clients.items():
            key = client.key.get_secret_value()
            if key and secrets.compare_digest(credentials.credentials.encode(), key.encode()):
                return Principal(name=name, role=client.role)
    raise HTTPException(
        status_code=401,
        detail="Нужен действующий ключ клиента",
        headers={"WWW-Authenticate": "Bearer"},
    )


def require_admin(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Нужна роль администратора")
    return principal


def require_approver(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != "approver":
        raise HTTPException(status_code=403, detail="Нужна роль утверждающего")
    return principal


def require_observer(principal: Annotated[Principal, Depends(authenticate)]) -> Principal:
    if principal.role != "observer":
        raise HTTPException(status_code=403, detail="Нужна роль источника метрик")
    return principal


Reader = Annotated[Principal, Depends(authenticate)]
Admin = Annotated[Principal, Depends(require_admin)]
Approver = Annotated[Principal, Depends(require_approver)]
Observer = Annotated[Principal, Depends(require_observer)]
