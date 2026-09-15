import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request

# Imported ALIASED, and the alias is load-bearing. `get_audit_logs` below declares a
# query parameter literally named `status` (the public wire name external callers send),
# so inside that function a plain `from fastapi import status` would still be shadowed by
# the parameter: `status.HTTP_500_INTERNAL_SERVER_ERROR` would resolve to the parameter
# (`None` on a request that omits the filter) and raise AttributeError on the very error
# path it guards. Renaming the parameter instead would change the public query-param name.
from fastapi import status as http_status
from pydantic import BaseModel

from .audit import AuditLogService
from .auth import requires_permission
from .dependencies import get_audit_service

logger = logging.getLogger(__name__)


# Define request and response models
class AuditLogResponse(BaseModel):
    id: int
    timestamp: datetime
    actor_id: int | None = None
    actor_type: str
    action_type: str
    resource_type: str
    resource_id: str | None = None
    status: str
    details: dict[str, Any] | None = None
    request_id: str | None = None
    ip_address: str | None = None


# Create the router
router = APIRouter(
    tags=["audit"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
    },
)


# API Endpoints
@router.get("/logs", response_model=list[AuditLogResponse])
async def get_audit_logs(
    current_user: Annotated[dict[str, Any], Depends(requires_permission("log:read"))],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
    request: Request = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    actor_id: int | None = None,
    actor_type: str | None = None,
    action_type: str | None = None,
    resource_type: str | None = None,
    resource_id: str | None = None,
    status: str | None = None,
    limit: int = Query(100, le=1000),
    offset: int = Query(0, ge=0),
):
    """
    Get audit logs with optional filtering.

    Args:
        current_user: The authenticated user with log:read permission
        audit_service: The audit log service
        request: FastAPI request object
        start_time: Filter logs after this time
        end_time: Filter logs before this time
        actor_id: Filter logs by actor ID
        actor_type: Filter logs by actor type
        action_type: Filter logs by action type
        resource_type: Filter logs by resource type
        resource_id: Filter logs by resource ID
        status: Filter logs by status
        limit: Maximum number of logs to return (max 1000)
        offset: Offset for pagination

    Returns:
        List of audit log entries
    """
    try:
        logs = await audit_service.get_logs(
            start_time=start_time,
            end_time=end_time,
            actor_id=actor_id,
            actor_type=actor_type,
            action_type=action_type,
            resource_type=resource_type,
            resource_id=resource_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        # Log the audit log retrieval (meta-logging)
        filter_details = {}
        if start_time:
            filter_details["start_time"] = start_time.isoformat()
        if end_time:
            filter_details["end_time"] = end_time.isoformat()
        if actor_id:
            filter_details["actor_id"] = actor_id
        if actor_type:
            filter_details["actor_type"] = actor_type
        if action_type:
            filter_details["action_type"] = action_type
        if resource_type:
            filter_details["resource_type"] = resource_type
        if resource_id:
            filter_details["resource_id"] = resource_id
        if status:
            filter_details["status"] = status

        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="read",
            resource_type="audit_logs",
            resource_id=None,
            status="success",
            details={
                "filters": filter_details,
                "limit": limit,
                "offset": offset,
                "result_count": len(logs),
            },
            request=request,
        )

        return logs

    except Exception as e:
        logger.error(f"Failed to retrieve audit logs: {e}")

        # Log the failure
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="read",
            resource_type="audit_logs",
            resource_id=None,
            status="failure",
            details={"error": str(e)},
            request=request,
        )

        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve audit logs: {e}",
        )
