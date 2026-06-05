import secrets
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from passlib.hash import bcrypt
from . import config

security = HTTPBasic(realm="Server Panel")


def require_admin(credentials: HTTPBasicCredentials = Depends(security)) -> str:
    correct_user = secrets.compare_digest(
        credentials.username.encode(), config.ADMIN_USER.encode()
    )
    correct_pwd = False
    if config.ADMIN_PASSWORD_HASH:
        try:
            correct_pwd = bcrypt.verify(credentials.password, config.ADMIN_PASSWORD_HASH)
        except Exception:
            correct_pwd = False
    if not (correct_user and correct_pwd):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
            headers={"WWW-Authenticate": 'Basic realm="Server Panel"'},
        )
    return credentials.username
