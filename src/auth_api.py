import logging
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    Body,
    Depends,
    HTTPException,
    Request,
    status,
)
from pydantic import BaseModel, Field

from .audit import AuditLogService

# Import directly from auth.py
from .auth import AuthService, get_current_user, requires_permission
from .dependencies import get_audit_service, get_auth_service

logger = logging.getLogger(__name__)


# Define request and response models
class Token(BaseModel):
    access_token: str
    token_type: str


class UserCredentials(BaseModel):
    username: str = Field(..., description="Username for authentication")
    password: str = Field(..., description="Password for authentication")


class ApiKeyAuth(BaseModel):
    api_key: str = Field(..., description="API key for authentication")


class UserCreate(BaseModel):
    username: str = Field(..., description="Username for the new user")
    password: str | None = Field(None, description="Password for human users")
    roles: list[str] = Field(default=[], description="Roles to assign to the user")
    generate_api_key: bool = Field(
        default=False, description="Whether to generate an API key for this user"
    )


class UserResponse(BaseModel):
    id: int
    username: str
    is_active: bool
    roles: list[str]
    api_key: str | None = None


class ApiKeyResponse(BaseModel):
    api_key: str
    username: str


class RoleResponse(BaseModel):
    id: int
    name: str
    description: str | None = None
    permissions: list[str]


class PermissionResponse(BaseModel):
    permissions: list[str] = []


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    token_type: str = "bearer"


class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str | None = None
    roles: list[str] = Field(default=[], description="Initial roles to assign")


class RegisterResponse(BaseModel):
    id: int
    username: str


class UserInfoResponse(BaseModel):
    id: int
    username: str
    email: str | None = None
    is_active: bool
    roles: list[str] = []
    permissions: list[str] = []


class ReadUserResponse(BaseModel):
    id: int
    username: str
    email: str | None = None


class UserUpdate(BaseModel):
    roles: list[str] | None = Field(
        None, description="List of role names to assign (replaces existing roles)"
    )
    is_active: bool | None = Field(None, description="Set user active status")
    email: str | None = Field(None, description="Update user email")


# Create the router
router = APIRouter(
    tags=["authentication"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
    },
)


# API Endpoints
@router.post("/login", response_model=LoginResponse, summary="Log in")
async def login(
    request: Request,
    login_data: LoginRequest,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Log in with username and password.

    Returns a JWT token that can be used to authenticate further requests.
    """
    user = await auth_service.authenticate_user(
        login_data.username, login_data.password
    )
    log_details = {"username": login_data.username}
    actor_id = None
    actor_type = "human"

    if not user:
        log_details["reason"] = "Invalid credentials"
        await audit_service.log_event(
            actor_id=None,
            actor_type=actor_type,
            action_type="login",
            resource_type="session",
            resource_id=login_data.username,
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    actor_id = user["id"]
    if not user.get("is_active", True):
        log_details["reason"] = "User account is inactive"
        await audit_service.log_event(
            actor_id=actor_id,
            actor_type=actor_type,
            action_type="login",
            resource_type="session",
            resource_id=login_data.username,
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User account is inactive",
        )

    try:
        token = await auth_service.create_access_token(
            data={"sub": str(user["id"]), "username": user["username"]}
        )

        await audit_service.log_event(
            actor_id=actor_id,
            actor_type=actor_type,
            action_type="login",
            resource_type="session",
            resource_id=login_data.username,
            status="success",
            details=log_details,
            request=request,
        )

        return LoginResponse(token=token)
    except Exception as e:
        logger.exception(f"Login error after authentication for {login_data.username}")
        log_details["error"] = str(e)
        await audit_service.log_event(
            actor_id=actor_id,
            actor_type=actor_type,
            action_type="login",
            resource_type="session",
            resource_id=login_data.username,
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Login failed due to an internal error",
        )


@router.post("/register", response_model=RegisterResponse, summary="Register new user")
async def register(
    register_data: RegisterRequest,
    request: Request,
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Register a new user.

    Returns the user ID and username of the created user.
    """
    log_details = {
        "username": register_data.username,
        "email": register_data.email,
        "initial_roles": register_data.roles,
    }
    try:
        if not register_data.password:
            raise ValueError("Password is required for registration")
        hashed_password = auth_service.hash_password(register_data.password)

        user_id = await auth_service.db.create_user(
            register_data.username, hashed_password, None, register_data.email
        )

        if register_data.roles:
            try:
                await auth_service.db.update_user_roles(user_id, register_data.roles)
                logger.info(
                    f"Assigned initial roles {register_data.roles} to new user {user_id}"
                )
            except ValueError as role_err:
                logger.warning(
                    f"Could not assign initial roles to user {user_id}: {role_err}"
                )
                log_details["role_assignment_warning"] = str(role_err)

        await audit_service.log_event(
            actor_id=None,
            actor_type="system",
            action_type="register",
            resource_type="user",
            resource_id=str(user_id),
            status="success",
            details=log_details,
            request=request,
        )

        return RegisterResponse(id=user_id, username=register_data.username)

    except ValueError as e:
        log_details["error"] = str(e)
        await audit_service.log_event(
            actor_id=None,
            actor_type="system",
            action_type="register",
            resource_type="user",
            resource_id=register_data.username,
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception:
        logger.exception(f"User registration failed for {register_data.username}")
        log_details["error"] = "Internal server error during registration."
        await audit_service.log_event(
            actor_id=None,
            actor_type="system",
            action_type="register",
            resource_type="user",
            resource_id=register_data.username,
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="User registration failed.",
        )


@router.get("/me", response_model=UserInfoResponse, summary="Get current user info")
async def get_user_info(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Get information about the currently authenticated user.
    """
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not identify user"
        )

    user_details = await auth_service.db.get_user_by_id(user_id)
    if not user_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    permissions = await auth_service.get_user_permissions(user_id)
    roles = await auth_service.db.get_user_roles(user_id)
    role_names = [r["name"] for r in roles]

    return UserInfoResponse(
        id=user_details["id"],
        username=user_details["username"],
        email=user_details.get("email"),
        is_active=user_details.get("is_active", True),
        roles=role_names,
        permissions=list(permissions),
    )


@router.get(
    "/users/{user_id}", response_model=UserInfoResponse, summary="Get user by ID"
)
async def get_user(
    user_id: int,
    current_user: Annotated[dict[str, Any], Depends(requires_permission("user:read"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    Get information about a specific user by their ID.
    Requires 'user:read' permission.
    """
    user_details = await auth_service.db.get_user_by_id(user_id)
    if not user_details:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    permissions = await auth_service.get_user_permissions(user_id)
    roles = await auth_service.db.get_user_roles(user_id)
    role_names = [r["name"] for r in roles]

    return UserInfoResponse(
        id=user_details["id"],
        username=user_details["username"],
        email=user_details.get("email"),
        is_active=user_details.get("is_active", True),
        roles=role_names,
        permissions=list(permissions),
    )


@router.get("/users", response_model=list[UserInfoResponse], summary="List all users")
async def list_users(
    current_user: Annotated[dict[str, Any], Depends(requires_permission("user:list"))],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
):
    """
    List all users in the system.
    Requires 'user:list' permission.
    """
    users_list = await auth_service.db.list_users()
    response_list = []
    for user in users_list:
        user_id = user["id"]
        permissions = await auth_service.get_user_permissions(user_id)
        roles = await auth_service.db.get_user_roles(user_id)
        role_names = [r["name"] for r in roles]
        response_list.append(
            UserInfoResponse(
                id=user["id"],
                username=user["username"],
                email=user.get("email"),
                is_active=user.get("is_active", True),
                roles=role_names,
                permissions=list(permissions),
            )
        )
    return response_list


@router.put(
    "/users/{user_id}",
    response_model=UserInfoResponse,
    summary="Update user information",
)
async def update_user(
    user_id: int,
    user_update_data: UserUpdate,
    request: Request,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("user:update"))
    ],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Update a user's roles or active status.
    Requires 'user:update' permission.
    """
    target_user = await auth_service.db.get_user_by_id(user_id)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with ID {user_id} not found",
        )

    updated_fields = user_update_data.model_dump(exclude_unset=True)
    log_details = {
        "target_user_id": user_id,
        "updated_fields": list(updated_fields.keys()),
    }

    try:
        if user_update_data.roles is not None:
            await auth_service.db.update_user_roles(user_id, user_update_data.roles)
            log_details["new_roles"] = user_update_data.roles

        if user_update_data.is_active is not None:
            await auth_service.db.set_user_active_status(
                user_id, user_update_data.is_active
            )
            log_details["new_active_status"] = user_update_data.is_active

        if not updated_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No update data provided",
            )

        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type=current_user.get("actor_type", "human"),
            action_type="update",
            resource_type="user",
            resource_id=str(user_id),
            status="success",
            details=log_details,
            request=request,
        )

        updated_user_details = await auth_service.db.get_user_by_id(user_id)
        permissions = await auth_service.get_user_permissions(user_id)
        roles = await auth_service.db.get_user_roles(user_id)
        role_names = [r["name"] for r in roles]

        return UserInfoResponse(
            id=updated_user_details["id"],
            username=updated_user_details["username"],
            email=updated_user_details.get("email"),
            is_active=updated_user_details.get("is_active", True),
            roles=role_names,
            permissions=list(permissions),
        )

    except ValueError as e:
        log_details["error"] = str(e)
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type=current_user.get("actor_type", "human"),
            action_type="update",
            resource_type="user",
            resource_id=str(user_id),
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    except Exception:
        logger.exception(f"Error updating user {user_id}")
        log_details["error"] = "Internal server error during update."
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type=current_user.get("actor_type", "human"),
            action_type="update",
            resource_type="user",
            resource_id=str(user_id),
            status="failure",
            details=log_details,
            request=request,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update user {user_id}",
        )


@router.get(
    "/permissions",
    response_model=PermissionResponse,
    summary="Get current user permissions",
)
async def get_permissions(
    current_user: Annotated[dict[str, Any], Depends(get_current_user)],
    auth_service: AuthService = Depends(get_auth_service),
):
    """
    Get a list of all permissions assigned to the currently authenticated user.
    """
    user_id = current_user.get("id")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not identify user"
        )

    permissions_set = await auth_service.get_user_permissions(user_id)
    return PermissionResponse(permissions=list(permissions_set))


@router.post(
    "/debug-token",
    summary="Debug Token Validation",
    tags=["debug"],
    include_in_schema=False,
)
async def debug_token(
    token: str = Body(..., embed=True),
    request: Request = None,
    auth_service: AuthService = Depends(get_auth_service),
):
    """Helper endpoint to decode and validate a provided token."""
    try:
        payload = await auth_service.decode_token(token)
        if payload.get("_jwt_decode_failed"):
            user = await auth_service.authenticate_api_key(token)
            if user:
                return {"token_type": "api_key", "valid": True, "user": user}
            else:
                return {
                    "token_type": "unknown",
                    "valid": False,
                    "error": "Invalid JWT or API key",
                }
        else:
            user_id = int(payload.get("sub"))
            user_info = await auth_service.db.get_user_by_id(user_id)
            permissions = await auth_service.get_user_permissions(user_id)
            return {
                "token_type": "jwt",
                "valid": True,
                "payload": payload,
                "user_info": user_info,
                "permissions": list(permissions),
            }
    except HTTPException as e:
        return {"token_type": "jwt", "valid": False, "error": e.detail}
    except Exception as e:
        logger.exception("Debug token error")
        return {
            "token_type": "unknown",
            "valid": False,
            "error": f"Internal error: {e}",
        }
