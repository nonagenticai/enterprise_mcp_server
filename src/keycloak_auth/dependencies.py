"""FastAPI dependencies for authentication."""

from fastapi import HTTPException, Request, status, Depends

from .models import KeycloakUser


def get_current_user(request: Request) -> KeycloakUser:
    """Get authenticated user from request.
    
    Usage:
        @app.get("/api/items")
        async def get_items(user: KeycloakUser = Depends(get_current_user)):
            return {"user": user.preferred_username}
    """
    if not hasattr(request.state, "user"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required"
        )
    return request.state.user


def require_role(role: str):
    """Require specific role.
    
    Usage:
        @app.post("/admin/endpoint")
        async def admin_only(user: KeycloakUser = Depends(require_role("admin"))):
            return {"message": "Admin access"}
    """
    def checker(request: Request) -> KeycloakUser:
        user = get_current_user(request)
        if not user.has_realm_role(role):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{role}' required"
            )
        return user
    return checker


def require_any_role(*roles: str):
    """Require any of specified roles.
    
    Usage:
        @app.get("/editor/endpoint")
        async def editor(user: KeycloakUser = Depends(require_any_role("editor", "admin"))):
            return {"message": "Access granted"}
    """
    def checker(request: Request) -> KeycloakUser:
        user = get_current_user(request)
        if not any(user.has_realm_role(r) for r in roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"One of roles required: {', '.join(roles)}"
            )
        return user
    return checker
