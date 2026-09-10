import logging
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from .audit import AuditLogService
from .auth import requires_permission
from .dependencies import get_audit_service, get_db
from .mcp_postgres_db import MCPPostgresDB

logger = logging.getLogger(__name__)


# Define request and response models
class ToolVersionResponse(BaseModel):
    tool_id: str
    version_number: int
    code: str
    created_at: datetime


class ToolVersionsResponse(BaseModel):
    tool_id: str
    tool_name: str
    current_version: int
    versions: list[ToolVersionResponse]


class RestoreVersionRequest(BaseModel):
    version_number: int = Field(..., description="Version number to restore")


# Create the router
router = APIRouter(
    prefix="/tool-versions",
    tags=["tool-versions"],
    responses={
        401: {"description": "Unauthorized"},
        403: {"description": "Forbidden"},
        404: {"description": "Not found"},
    },
)


# API Endpoints
@router.get("/{tool_name}", response_model=ToolVersionsResponse)
async def get_tool_versions(
    tool_name: str,
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
    current_user: Annotated[dict[str, Any], Depends(requires_permission("tool:read"))],
    request: Request = None,
):
    """
    Get all versions of a tool.

    Args:
        tool_name: Name of the tool to get versions for

    Returns:
        Tool versions information

    Raises:
        HTTPException: If tool not found
    """
    try:
        # Get tool details
        tool = await db.get_tool_by_name(tool_name)
        if not tool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool with name '{tool_name}' not found",
            )

        # Get tool versions
        versions = await db.get_tool_versions(tool["tool_id"])

        # Find current version
        current_version = max(v["version_number"] for v in versions) if versions else 0

        # Log the access
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="read",
            resource_type="tool_versions",
            resource_id=tool["tool_id"],
            status="success",
            details={"tool_name": tool_name, "version_count": len(versions)},
            request=request,
        )

        return {
            "tool_id": tool["tool_id"],
            "tool_name": tool_name,
            "current_version": current_version,
            "versions": versions,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get tool versions for '{tool_name}': {e}")

        # Log the failure
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="read",
            resource_type="tool_versions",
            resource_id=None,
            status="failure",
            details={"tool_name": tool_name, "error": str(e)},
            request=request,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get tool versions: {e}",
        )


@router.post("/{tool_name}/restore", status_code=status.HTTP_200_OK)
async def restore_tool_version(
    tool_name: str,
    restore_data: RestoreVersionRequest,
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:update"))
    ],
    request: Request = None,
):
    """
    Restore a previous version of a tool.

    Args:
        tool_name: Name of the tool to restore a version for
        restore_data: Data with version number to restore

    Returns:
        Success message

    Raises:
        HTTPException: If tool not found or version not found
    """
    try:
        # Get tool details
        tool = await db.get_tool_by_name(tool_name)
        if not tool:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Tool with name '{tool_name}' not found",
            )

        # Get tool versions
        versions = await db.get_tool_versions(tool["tool_id"])
        version_numbers = [v["version_number"] for v in versions]

        # Check if version exists
        if restore_data.version_number not in version_numbers:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Version {restore_data.version_number} not found for tool '{tool_name}'",
            )

        # Get the version to restore
        version_to_restore = next(
            v for v in versions if v["version_number"] == restore_data.version_number
        )

        # Check if it's already the current version
        current_version = max(version_numbers)
        if restore_data.version_number == current_version:
            return {
                "message": f"Version {restore_data.version_number} is already the current version"
            }

        # Update the tool with the version's code
        is_multi_file = tool.get("is_multi_file", False)

        if is_multi_file:
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail="Restoring versions of multi-file tools is not yet implemented",
            )
        else:
            success = await db.update_tool(
                name=tool_name,
                description=tool["description"],
                code=version_to_restore["code"],
            )

            if not success:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to restore version {restore_data.version_number} for tool '{tool_name}'",
                )

        # Log the version restoration
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="update",
            resource_type="tool",
            resource_id=tool["tool_id"],
            status="success",
            details={
                "tool_name": tool_name,
                "action": "restore_version",
                "restored_version": restore_data.version_number,
                "from_version": current_version,
            },
            request=request,
        )

        return {
            "message": f"Successfully restored version {restore_data.version_number} for tool '{tool_name}'"
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore version for tool '{tool_name}': {e}")

        # Log the failure
        await audit_service.log_event(
            actor_id=current_user["id"],
            actor_type="human",
            action_type="update",
            resource_type="tool",
            resource_id=None,
            status="failure",
            details={
                "tool_name": tool_name,
                "action": "restore_version",
                "version": restore_data.version_number,
                "error": str(e),
            },
            request=request,
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to restore tool version: {e}",
        )
