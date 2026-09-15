"""
Tool management API endpoints for backup and restore functionality.
"""

import datetime
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Annotated, Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Body,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from fastmcp import FastMCP
from pydantic import BaseModel, Field
from uuid_v7.base import uuid7

from .audit import AuditLogService
from .auth import AuthService, get_current_user, requires_permission
from .dependencies import get_audit_service, get_auth_service, get_db, get_tool_registry
from .mcp_postgres_db import MCPPostgresDB

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["tools"],
    responses={404: {"description": "Not found"}},
)

# Define backup directory (create if it doesn't exist)
BACKUP_DIR = Path("backups")
BACKUP_DIR.mkdir(exist_ok=True)


# Tool Models for API
class ToolInfo(BaseModel):
    """Information about a tool"""

    name: str
    description: str | None = None
    version: str | None = None
    type: str | None = None


class ToolCreate(BaseModel):
    """Model for creating a single-file tool"""

    name: str = Field(..., description="Name of the tool", min_length=1, max_length=100)
    description: str = Field(
        ..., description="Description of what the tool does", max_length=1000
    )
    code: str = Field(..., description="Python code for the tool", min_length=1)
    replace_existing: bool = Field(
        False, description="Whether to replace an existing tool with the same name"
    )


class MultiFileToolCreate(BaseModel):
    """Model for creating a multi-file tool"""

    name: str = Field(..., description="Name of the tool", min_length=1, max_length=100)
    description: str = Field(
        ..., description="Description of what the tool does", max_length=1000
    )
    entrypoint: str = Field(
        ..., description="Main file/function entry point (e.g., 'main.py')"
    )
    files: dict[str, str] = Field(
        ..., description="Dictionary of filename -> file content"
    )
    replace_existing: bool = Field(
        False, description="Whether to replace an existing tool with the same name"
    )
    tool_dir_uuid: str | None = Field(
        None, description="Optional tool directory UUID for grouping"
    )


class ToolResponse(BaseModel):
    """Response model for tool creation"""

    success: bool
    message: str
    tool_id: str | None = None
    tool_name: str
    created_at: str | None = None
    version_number: int | None = None


@router.post("/add", response_model=ToolResponse, summary="Add New Tool")
async def add_tool(
    tool_data: ToolCreate,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:create"))
    ],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Add a new single-file tool to the database.

    Args:
        tool_data: Tool creation data (name, description, code, etc.)
        current_user: The authenticated user with tool:create permission
        db: Database connection
        audit_service: Audit logging service

    Returns:
        ToolResponse with creation details
    """
    user_id = current_user.get("id")
    actor_type = current_user.get("actor_type", "human")

    try:
        # Validate tool name (basic checks - database will do more thorough validation)
        if not tool_data.name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tool name cannot be empty",
            )

        # Check for existing tool if not replacing
        if not tool_data.replace_existing:
            existing_tool = await db.get_tool_by_name(tool_data.name.strip())
            if existing_tool:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tool '{tool_data.name}' already exists. Use replace_existing=true to overwrite.",
                )

        # Add the tool to database
        tool_id = await db.add_tool(
            name=tool_data.name.strip(),
            description=tool_data.description.strip(),
            code=tool_data.code,
            created_by=user_id,
            replace_existing=tool_data.replace_existing,
        )

        # Get the created tool details for response
        created_tool = await db.get_tool_by_name(tool_data.name.strip())

        response = ToolResponse(
            success=True,
            message=f"Tool '{tool_data.name}' {'replaced' if tool_data.replace_existing else 'created'} successfully",
            tool_id=tool_id,
            tool_name=tool_data.name,
            created_at=created_tool.get("created_at") if created_tool else None,
            version_number=1,  # First version
        )

        # Log successful tool creation
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_tool",
            resource_type="tool",
            resource_id=tool_id,
            status="success",
            details={
                "tool_name": tool_data.name,
                "description": (
                    tool_data.description[:100] + "..."
                    if len(tool_data.description) > 100
                    else tool_data.description
                ),
                "code_length": len(tool_data.code),
                "replaced_existing": tool_data.replace_existing,
            },
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as ve:
        # Database validation errors
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_tool",
            resource_type="tool",
            resource_id=tool_data.name,
            status="failure",
            details={
                "tool_name": tool_data.name,
                "error": "Validation error",
                "error_details": str(ve),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Tool validation failed: {ve!s}",
        )
    except Exception as e:
        logger.exception(f"Error creating tool '{tool_data.name}'")

        # Log failure
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_tool",
            resource_type="tool",
            resource_id=tool_data.name,
            status="failure",
            details={
                "tool_name": tool_data.name,
                "error": "Unexpected error",
                "error_details": str(e),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating tool: {e!s}",
        )


@router.post(
    "/add-multi", response_model=ToolResponse, summary="Add New Multi-File Tool"
)
async def add_multi_file_tool(
    tool_data: MultiFileToolCreate,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:create"))
    ],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Add a new multi-file tool to the database.

    Args:
        tool_data: Multi-file tool creation data (name, description, entrypoint, files, etc.)
        current_user: The authenticated user with tool:create permission
        db: Database connection
        audit_service: Audit logging service

    Returns:
        ToolResponse with creation details
    """
    user_id = current_user.get("id")
    actor_type = current_user.get("actor_type", "human")

    try:
        # Validate tool name
        if not tool_data.name.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Tool name cannot be empty",
            )

        # Validate files
        if not tool_data.files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Multi-file tool must contain at least one file",
            )

        # Check if entrypoint file exists in files dict
        if tool_data.entrypoint not in tool_data.files:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Entrypoint file '{tool_data.entrypoint}' not found in files",
            )

        # Check for existing tool if not replacing
        if not tool_data.replace_existing:
            existing_tool = await db.get_tool_by_name(tool_data.name.strip())
            if existing_tool:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Tool '{tool_data.name}' already exists. Use replace_existing=true to overwrite.",
                )

        # Generate tool_dir_uuid if not provided
        tool_dir_uuid = (
            tool_data.tool_dir_uuid if tool_data.tool_dir_uuid else str(uuid7())
        )

        # Add the multi-file tool to database
        tool_id = await db.add_multi_file_tool(
            name=tool_data.name.strip(),
            description=tool_data.description.strip(),
            entrypoint=tool_data.entrypoint,
            files=tool_data.files,
            created_by=user_id,
            tool_dir_uuid=tool_dir_uuid,
            replace_existing=tool_data.replace_existing,
        )

        # Get the created tool details for response
        created_tool = await db.get_tool_by_name(tool_data.name.strip())

        response = ToolResponse(
            success=True,
            message=f"Multi-file tool '{tool_data.name}' {'replaced' if tool_data.replace_existing else 'created'} successfully",
            tool_id=tool_id,
            tool_name=tool_data.name,
            created_at=created_tool.get("created_at") if created_tool else None,
            version_number=1,  # First version
        )

        # Log successful tool creation
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_multi_file_tool",
            resource_type="tool",
            resource_id=tool_id,
            status="success",
            details={
                "tool_name": tool_data.name,
                "description": (
                    tool_data.description[:100] + "..."
                    if len(tool_data.description) > 100
                    else tool_data.description
                ),
                "entrypoint": tool_data.entrypoint,
                "file_count": len(tool_data.files),
                "files": list(tool_data.files.keys()),
                "tool_dir_uuid": tool_dir_uuid,
                "replaced_existing": tool_data.replace_existing,
            },
        )

        return response

    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except ValueError as ve:
        # Database validation errors
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_multi_file_tool",
            resource_type="tool",
            resource_id=tool_data.name,
            status="failure",
            details={
                "tool_name": tool_data.name,
                "error": "Validation error",
                "error_details": str(ve),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Multi-file tool validation failed: {ve!s}",
        )
    except Exception as e:
        logger.exception(f"Error creating multi-file tool '{tool_data.name}'")

        # Log failure
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="create_multi_file_tool",
            resource_type="tool",
            resource_id=tool_data.name,
            status="failure",
            details={
                "tool_name": tool_data.name,
                "error": "Unexpected error",
                "error_details": str(e),
            },
        )

        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error creating multi-file tool: {e!s}",
        )


@router.get("/backup", summary="Backup All Tools")
async def backup_tools(
    background_tasks: BackgroundTasks,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:backup"))
    ],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
    include_versions: bool = Query(
        True, description="Include all versions of tools in backup"
    ),
):
    """
    Generate a backup file containing all tools.
    This is processed as a background task to prevent timeouts on large backups.

    Args:
        background_tasks: FastAPI BackgroundTasks for async processing
        include_versions: Whether to include all versions of tools or just the latest
        current_user: The authenticated user with tool:backup permission
        db: Database connection
        audit_service: Audit logging service

    Returns:
        Object with backup job details and status
    """
    # Generate a unique backup ID and filename
    backup_id = str(uuid7())
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filename = f"tool_backup_{timestamp}_{backup_id}.json"

    # Create event logger and add task to background
    user_id = current_user.get("id")
    actor_type = current_user.get("actor_type", "human")

    # Log the start of the backup process
    await audit_service.log_event(
        actor_id=user_id,
        actor_type=actor_type,
        action_type="backup",
        resource_type="tools",
        resource_id=backup_id,
        status="started",
        details={"filename": filename, "include_versions": include_versions},
    )

    # Add the backup task to run in the background
    background_tasks.add_task(
        _generate_backup,
        db=db,
        backup_id=backup_id,
        filename=filename,
        include_versions=include_versions,
        user_id=user_id,
        actor_type=actor_type,
        audit_service=audit_service,
    )

    return {
        "status": "backup_started",
        "backup_id": backup_id,
        "filename": filename,
        "message": "Backup generation has been started as a background task.",
        "check_status_url": f"/tools/backup/status/{backup_id}",
    }


@router.get("/backup/status/{backup_id}", summary="Check Backup Status")
async def check_backup_status(
    backup_id: str,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:backup"))
    ],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Check the status of a backup job.

    Args:
        backup_id: The ID of the backup job
        current_user: The authenticated user with tool:backup permission
        audit_service: Audit logging service

    Returns:
        Current status of the backup job
    """
    try:
        # Search for audit log entries for this backup ID
        logs = await audit_service.get_logs(
            resource_id=backup_id, resource_type="tools", action_type="backup", limit=10
        )

        if not logs:
            raise HTTPException(
                status_code=404, detail=f"Backup job {backup_id} not found"
            )

        # Get the latest status
        latest_status = logs[0]["status"]

        # If successful, provide download link
        if latest_status == "success":
            # Look for filename in details
            filename = logs[0].get("details", {}).get("filename", "")
            file_path = BACKUP_DIR / filename

            if file_path.exists():
                return {
                    "status": "completed",
                    "backup_id": backup_id,
                    "filename": filename,
                    "download_url": f"/tools/backup/download/{filename}",
                    "timestamp": logs[0]["timestamp"],
                }
            else:
                return {
                    "status": "file_missing",
                    "backup_id": backup_id,
                    "message": "Backup was completed but the file is missing.",
                    "timestamp": logs[0]["timestamp"],
                }
        elif latest_status == "failure":
            error_message = logs[0].get("details", {}).get("error", "Unknown error")
            return {
                "status": "failed",
                "backup_id": backup_id,
                "error": error_message,
                "timestamp": logs[0]["timestamp"],
            }
        else:
            # Still in progress
            return {
                "status": "in_progress",
                "backup_id": backup_id,
                "message": "Backup is still being generated.",
                "timestamp": logs[0]["timestamp"],
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error checking backup status")
        raise HTTPException(
            status_code=500, detail=f"Error checking backup status: {e!s}"
        )


@router.get("/backup/download/{filename}", summary="Download Backup File")
async def download_backup(
    filename: str,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:backup"))
    ],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Download a generated backup file.

    Args:
        filename: The name of the backup file to download
        current_user: The authenticated user with tool:backup permission
        audit_service: Audit logging service

    Returns:
        The backup file as a download
    """
    # Validate filename format and path
    if (
        ".." in filename
        or "/" in filename
        or "\\" in filename
        or not filename.startswith("tool_backup_")
    ):
        raise HTTPException(status_code=400, detail="Invalid filename format")

    file_path = BACKUP_DIR / filename

    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Backup file {filename} not found")

    # Log the download
    user_id = current_user.get("id")
    actor_type = current_user.get("actor_type", "human")

    await audit_service.log_event(
        actor_id=user_id,
        actor_type=actor_type,
        action_type="download",
        resource_type="backup",
        resource_id=filename,
        status="success",
        details={"filename": filename},
    )

    return FileResponse(
        path=file_path, filename=filename, media_type="application/json"
    )


@router.post("/restore", summary="Restore Tools from Backup")
async def restore_tools(
    background_tasks: BackgroundTasks,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:restore"))
    ],
    db: Annotated[MCPPostgresDB, Depends(get_db)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
    backup_file: UploadFile = File(...),
    overwrite_existing: bool = Body(False),
    skip_conflicts: bool = Body(True),
):
    """
    Restore tools from a backup file.

    Args:
        background_tasks: FastAPI BackgroundTasks for async processing
        backup_file: The backup file to restore from
        overwrite_existing: Whether to overwrite existing tools
        skip_conflicts: If True, skip conflicting tools; if False, fail on conflict
        current_user: The authenticated user with tool:restore permission
        db: Database connection
        audit_service: Audit logging service

    Returns:
        Object with restore job details and status
    """
    # Validate file format
    if not backup_file.filename.endswith(".json"):
        raise HTTPException(status_code=400, detail="Backup file must be a JSON file")

    # Generate a unique restore ID
    restore_id = str(uuid7())

    # Save the uploaded file to a temporary location
    temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    try:
        # Read and write in chunks to handle large files
        contents = await backup_file.read()
        temp_file.write(contents)
        temp_file.close()

        # Log the start of the restore process
        user_id = current_user.get("id")
        actor_type = current_user.get("actor_type", "human")

        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="restore",
            resource_type="tools",
            resource_id=restore_id,
            status="started",
            details={
                "filename": backup_file.filename,
                "overwrite_existing": overwrite_existing,
                "skip_conflicts": skip_conflicts,
            },
        )

        # Add the restore task to run in the background
        background_tasks.add_task(
            _process_restore,
            db=db,
            restore_id=restore_id,
            temp_file_path=temp_file.name,
            overwrite_existing=overwrite_existing,
            skip_conflicts=skip_conflicts,
            user_id=user_id,
            actor_type=actor_type,
            audit_service=audit_service,
        )

        return {
            "status": "restore_started",
            "restore_id": restore_id,
            "message": "Restore process has been started as a background task.",
            "check_status_url": f"/tools/restore/status/{restore_id}",
        }
    except Exception as e:
        # Clean up the temporary file
        if os.path.exists(temp_file.name):
            os.unlink(temp_file.name)
        logger.exception("Error starting restore process")
        raise HTTPException(
            status_code=500, detail=f"Error starting restore process: {e!s}"
        )


@router.get("/restore/status/{restore_id}", summary="Check Restore Status")
async def check_restore_status(
    restore_id: str,
    current_user: Annotated[
        dict[str, Any], Depends(requires_permission("tool:restore"))
    ],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """
    Check the status of a restore job.

    Args:
        restore_id: The ID of the restore job
        current_user: The authenticated user with tool:restore permission
        audit_service: Audit logging service

    Returns:
        Current status of the restore job
    """
    try:
        # Search for audit log entries for this restore ID
        logs = await audit_service.get_logs(
            resource_id=restore_id,
            resource_type="tools",
            action_type="restore",
            limit=10,
        )

        if not logs:
            raise HTTPException(
                status_code=404, detail=f"Restore job {restore_id} not found"
            )

        # Get the latest status
        latest_status = logs[0]["status"]

        if latest_status == "success":
            # Return details of the restore
            stats = logs[0].get("details", {}).get("stats", {})
            return {
                "status": "completed",
                "restore_id": restore_id,
                "timestamp": logs[0]["timestamp"],
                "stats": stats,
            }
        elif latest_status == "failure":
            error_message = logs[0].get("details", {}).get("error", "Unknown error")
            return {
                "status": "failed",
                "restore_id": restore_id,
                "error": error_message,
                "timestamp": logs[0]["timestamp"],
            }
        else:
            # Still in progress
            return {
                "status": "in_progress",
                "restore_id": restore_id,
                "message": "Restore is still being processed.",
                "timestamp": logs[0]["timestamp"],
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error checking restore status")
        raise HTTPException(
            status_code=500, detail=f"Error checking restore status: {e!s}"
        )


# Add the list tools endpoint
@router.get("/list", response_model=list[ToolInfo], tags=["tools"])
async def list_tools(
    tool_registry: Annotated[FastMCP, Depends(get_tool_registry)],
    current_user: Annotated[dict, Depends(get_current_user)],
    auth_service: Annotated[AuthService, Depends(get_auth_service)],
    audit_service: Annotated[AuditLogService, Depends(get_audit_service)],
):
    """List all available tools with their metadata"""
    # Check permissions
    user_principal = current_user
    actor_type = user_principal.get(
        "actor_type", "human"
    )  # Get actor_type consistently

    if not await auth_service.check_permission(user_principal["id"], "tool:read"):
        # Log audit event for unauthorized access attempt
        await audit_service.log_event(
            actor_id=user_principal.get("id"),
            actor_type=actor_type,  # Use derived actor_type
            action_type="list_tools",  # Use action_type
            resource_type="tools",  # Use resource_type
            resource_id="tools",  # <-- Add this argument
            status="denied",
            details="Insufficient permissions: requires 'tool:read'",  # More specific detail
        )

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions to view tools",
        )

    # Get tools from registry using the FastMCP instance
    tools_data = []
    registered_tools = await tool_registry.get_tools()

    for name, tool_callable in registered_tools.items():
        # Try to get metadata attached to the tool function/wrapper
        description = getattr(tool_callable, "__doc__", None)
        version = getattr(tool_callable, "version", None)
        tool_type = getattr(tool_callable, "type", None)

        tools_data.append(
            ToolInfo(
                name=name, description=description, version=version, type=tool_type
            )
        )

    # Log successful tool listing
    await audit_service.log_event(
        actor_id=user_principal.get("id"),
        actor_type=actor_type,  # Use derived actor_type
        action_type="list_tools",  # Use action_type
        resource_type="tools",  # Use resource_type
        resource_id="tools",  # <-- Add this argument
        status="success",
        details=f"Listed {len(tools_data)} tools",
    )

    return tools_data


# ----- Background task functions -----


async def _generate_backup(
    db: MCPPostgresDB,
    backup_id: str,
    filename: str,
    include_versions: bool,
    user_id: str,
    actor_type: str,
    audit_service: AuditLogService,
):
    """
    Background task to generate a backup file.

    Args:
        db: Database connection
        backup_id: Unique ID for this backup job
        filename: Name of the backup file to create
        include_versions: Whether to include all versions
        user_id: ID of the user who initiated the backup
        actor_type: Type of actor (human, system, etc.)
        audit_service: Audit logging service
    """
    file_path = BACKUP_DIR / filename

    try:
        # Get all tools from the database
        tools = await db.get_all_tools_for_backup(include_versions=include_versions)

        # Generate backup metadata
        backup_data = {
            "metadata": {
                "backup_id": backup_id,
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "include_versions": include_versions,
                "tool_count": len(tools),
                "created_by": user_id,
                "format_version": "1.0",
            },
            "tools": tools,
        }

        # Write to file
        with open(file_path, "w") as f:
            json.dump(backup_data, f, indent=2)

        # Log success
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="backup",
            resource_type="tools",
            resource_id=backup_id,
            status="success",
            details={
                "filename": filename,
                "tool_count": len(tools),
                "file_size_bytes": os.path.getsize(file_path),
            },
        )

        logger.info(f"Backup completed: {filename} with {len(tools)} tools")

    except Exception as e:
        logger.exception(f"Error generating backup {backup_id}")

        # Log failure
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="backup",
            resource_type="tools",
            resource_id=backup_id,
            status="failure",
            details={"filename": filename, "error": str(e)},
        )

        # Clean up any partially created file
        if file_path.exists():
            try:
                os.unlink(file_path)
            except Exception as cleanup_err:
                logger.error(f"Error cleaning up failed backup file: {cleanup_err}")


async def _process_restore(
    db: MCPPostgresDB,
    restore_id: str,
    temp_file_path: str,
    overwrite_existing: bool,
    skip_conflicts: bool,
    user_id: str,
    actor_type: str,
    audit_service: AuditLogService,
):
    """
    Background task to process a restore operation.

    Args:
        db: Database connection
        restore_id: Unique ID for this restore job
        temp_file_path: Path to the temporary backup file
        overwrite_existing: Whether to overwrite existing tools
        skip_conflicts: If True, skip conflicting tools; if False, fail on conflict
        user_id: ID of the user who initiated the restore
        actor_type: Type of actor (human, system, etc.)
        audit_service: Audit logging service
    """
    try:
        # Read the backup file
        with open(temp_file_path, "r") as f:
            backup_data = json.load(f)

        # Validate backup format
        if not isinstance(backup_data, dict) or "tools" not in backup_data:
            raise ValueError("Invalid backup file format: missing 'tools' section")

        tools = backup_data.get("tools", [])
        metadata = backup_data.get("metadata", {})

        # Statistics for reporting
        stats = {
            "total": len(tools),
            "success": 0,
            "skipped": 0,
            "failed": 0,
            "errors": [],
        }

        # Process each tool
        for tool in tools:
            try:
                tool_name = tool.get("name")

                # Check if tool already exists
                existing_tool = await db.get_tool_by_name(tool_name)

                if existing_tool:
                    if not overwrite_existing:
                        if skip_conflicts:
                            logger.info(
                                f"Skipping existing tool '{tool_name}' (skip_conflicts=True)"
                            )
                            stats["skipped"] += 1
                            continue
                        else:
                            # Conflict and we're not skipping
                            raise ValueError(
                                f"Tool '{tool_name}' already exists and overwrite_existing is False"
                            )

                    # Overwrite existing tool
                    is_multi_file = tool.get("is_multi_file", False)

                    if is_multi_file:
                        # Handle multi-file tool
                        await db.add_multi_file_tool(
                            name=tool_name,
                            description=tool.get("description", ""),
                            entrypoint=tool.get(
                                "code", "main.py"
                            ),  # Entrypoint filename
                            files=tool.get("files", {}),  # Dictionary of files
                            created_by=user_id,
                            tool_dir_uuid=tool.get("tool_dir_id", str(uuid7())),
                            replace_existing=True,  # Force replacement
                        )
                    else:
                        # Single file tool
                        await db.add_tool(
                            name=tool_name,
                            description=tool.get("description", ""),
                            code=tool.get("code", ""),
                            created_by=user_id,
                            replace_existing=True,  # Force replacement
                        )
                else:
                    # New tool
                    is_multi_file = tool.get("is_multi_file", False)

                    if is_multi_file:
                        # Handle multi-file tool
                        await db.add_multi_file_tool(
                            name=tool_name,
                            description=tool.get("description", ""),
                            entrypoint=tool.get(
                                "code", "main.py"
                            ),  # Entrypoint filename
                            files=tool.get("files", {}),  # Dictionary of files
                            created_by=user_id,
                            tool_dir_uuid=tool.get("tool_dir_id", str(uuid7())),
                        )
                    else:
                        # Single file tool
                        await db.add_tool(
                            name=tool_name,
                            description=tool.get("description", ""),
                            code=tool.get("code", ""),
                            created_by=user_id,
                        )

                # Restore versions if they exist and we're dealing with a single-file tool
                if (
                    not is_multi_file
                    and "versions" in tool
                    and isinstance(tool["versions"], list)
                ):
                    tool_db_record = await db.get_tool_by_name(tool_name)
                    if tool_db_record:
                        tool_id = tool_db_record.get("id")

                        # Add each version
                        for version in tool["versions"]:
                            if version.get("is_current", False):
                                # Skip current version, it's already been added
                                continue

                            await db.add_tool_version(
                                tool_id=tool_id,
                                code=version.get("code", ""),
                                created_by=user_id,
                                description=version.get("description", ""),
                                # Optionally preserve original timestamps if available
                                created_at=version.get("created_at"),
                            )

                stats["success"] += 1

            except Exception as tool_err:
                logger.error(
                    f"Error restoring tool '{tool.get('name', 'unknown')}': {tool_err}"
                )
                stats["failed"] += 1
                stats["errors"].append(
                    {"tool": tool.get("name", "unknown"), "error": str(tool_err)}
                )

                # Only abort on error if we're not skipping conflicts
                if not skip_conflicts:
                    raise

        # Log success with statistics
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="restore",
            resource_type="tools",
            resource_id=restore_id,
            status="success",
            details={"stats": stats, "original_backup_metadata": metadata},
        )

        logger.info(
            f"Restore completed: {restore_id} with {stats['success']} successful, {stats['skipped']} skipped, {stats['failed']} failed"
        )

    except Exception as e:
        logger.exception(f"Error processing restore {restore_id}")

        # Log failure
        await audit_service.log_event(
            actor_id=user_id,
            actor_type=actor_type,
            action_type="restore",
            resource_type="tools",
            resource_id=restore_id,
            status="failure",
            details={"error": str(e)},
        )
    finally:
        # Clean up the temporary file
        try:
            if os.path.exists(temp_file_path):
                os.unlink(temp_file_path)
        except Exception as cleanup_err:
            logger.error(f"Error cleaning up temporary file: {cleanup_err}")
