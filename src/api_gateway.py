"""
API Gateway module for the MCP Server ecosystem.

This module implements a basic API Gateway that routes requests to the appropriate MCP servers:
- Main MCP server (default)
- Dynamic MCP server (for on-demand tool creation)
- Read-Only MCP server (for non-modifying operations)

This implements FR-GATEWAY-01, FR-GATEWAY-02, and FR-GATEWAY-07 from the roadmap.
"""

import os
import logging
import asyncio
import time
import json
from uuid_v7.base import uuid7
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple, Callable, Awaitable, cast

from fastapi import FastAPI, Request, Response, HTTPException, Depends, status, Query
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import redis.asyncio as redis

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("api_gateway")

# Configuration from environment variables with defaults
ENTERPRISE_MCP_SERVER_URL = os.getenv(
    "ENTERPRISE_MCP_SERVER_URL", "http://localhost:8030"
)
GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8000"))
GATEWAY_HOST = os.getenv("GATEWAY_HOST", "0.0.0.0")

# Redis configuration
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
DEFAULT_RATE_LIMIT = int(os.getenv("DEFAULT_RATE_LIMIT", "100"))  # Requests per minute
REDIS_ANALYTICS_TTL = int(
    os.getenv("REDIS_ANALYTICS_TTL", "604800")
)  # 7 days in seconds
REDIS_DOMAIN_TTL = int(os.getenv("REDIS_DOMAIN_TTL", "2592000"))  # 30 days in seconds

# Initialize Redis client
redis_client = None
try:
    redis_client = redis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
    logger.info(f"Initialized Redis client with URL: {REDIS_URL}")
except Exception as e:
    logger.error(f"Failed to initialize Redis client: {e}")
    # We'll continue without Redis and handle missing client in relevant functions

# CORS configuration
DEFAULT_CORS_ORIGINS = (
    "https://app.cursor.sh,https://cursor.sh,http://localhost:*,http://127.0.0.1:*"
)
CORS_ALLOWED_ORIGINS_STR = os.getenv("CORS_ALLOWED_ORIGINS", DEFAULT_CORS_ORIGINS)
CORS_ALLOWED_ORIGINS = [
    origin.strip() for origin in CORS_ALLOWED_ORIGINS_STR.split(",")
]

# Backend health check settings
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # seconds
HEALTH_CHECK_TIMEOUT = float(os.getenv("HEALTH_CHECK_TIMEOUT", "5.0"))  # seconds

# Backend health status
backend_health = {
    "main": {
        "url": ENTERPRISE_MCP_SERVER_URL,
        "healthy": False,
        "last_checked": 0,
        "error": None,
    }
}

# Domain mapping cache (will be populated from Redis)
# Maps domain names to backend configurations
domain_mappings = {}

# Pydantic models for API
from pydantic import BaseModel, Field


class DomainMapping(BaseModel):
    """Domain mapping configuration for the API Gateway."""

    domain: str = Field(..., description="Domain name (e.g., 'api.example.com')")
    backend_type: str = Field(
        ..., description="Backend type to route to ('main', 'dynamic', 'readonly')"
    )
    rate_limit: int = Field(
        DEFAULT_RATE_LIMIT,
        ge=1,
        description="Requests per minute allowed for this domain",
    )
    custom_headers: Dict[str, str] = Field(
        default_factory=dict, description="Custom headers to add to requests"
    )
    require_auth: bool = Field(
        True, description="Whether authentication is required for this domain"
    )
    enabled: bool = Field(True, description="Whether this domain mapping is enabled")
    description: Optional[str] = Field(
        None, description="Description of this domain mapping"
    )


# Create FastAPI application
app = FastAPI(
    title="MCP API Gateway",
    description="API Gateway for routing requests to appropriate MCP services",
    version="1.0.0",
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routing rules
# Define paths that should go to specific backends
DYNAMIC_PATHS = [
    "/api/dynamic",  # Path prefix for dynamic tool creation/management
    "/create-dynamic-tool",
    "/register-new-tool",
    "/register-multi-file-tool",
    "/register-openapi",
]

READONLY_PATHS = [
    "/api/readonly",  # Path prefix for read-only operations
    "/api/audit-logs/query",
    "/backup-tool",
]


# Utility functions
async def check_backend_health(backend_type: str, url: str) -> bool:
    """Check if a backend server is healthy by making a request to its health endpoint."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{url}/health", timeout=HEALTH_CHECK_TIMEOUT)
            if response.status_code == 200:
                logger.debug(f"{backend_type.upper()} backend is healthy: {url}")
                backend_health[backend_type]["healthy"] = True
                backend_health[backend_type]["last_checked"] = time.time()
                backend_health[backend_type]["error"] = None
                return True
            else:
                error_msg = f"Health check returned status {response.status_code}"
                logger.warning(
                    f"{backend_type.upper()} backend health check failed: {error_msg}"
                )
                backend_health[backend_type]["healthy"] = False
                backend_health[backend_type]["last_checked"] = time.time()
                backend_health[backend_type]["error"] = error_msg
                return False
    except Exception as e:
        error_msg = f"Health check error: {str(e)}"
        logger.warning(
            f"{backend_type.upper()} backend health check failed: {error_msg}"
        )
        backend_health[backend_type]["healthy"] = False
        backend_health[backend_type]["last_checked"] = time.time()
        backend_health[backend_type]["error"] = error_msg
        return False


async def load_domain_mappings():
    """Load domain mappings from Redis."""
    global domain_mappings
    if not redis_client:
        logger.warning("Redis not available, skipping domain mappings load")
        return

    try:
        # Get all domain mapping keys
        keys = await redis_client.keys("domain:*")
        for key in keys:
            domain = key.split(":", 1)[1]
            mapping_data = await redis_client.get(key)
            if mapping_data:
                try:
                    mapping = json.loads(mapping_data)
                    domain_mappings[domain] = mapping
                except json.JSONDecodeError:
                    logger.error(f"Invalid JSON in domain mapping for {domain}")

        logger.info(f"Loaded {len(domain_mappings)} domain mappings from Redis")
    except Exception as e:
        logger.error(f"Error loading domain mappings from Redis: {e}")


async def save_domain_mapping(mapping: DomainMapping) -> bool:
    """Save a domain mapping to Redis."""
    if not redis_client:
        logger.warning("Redis not available, cannot save domain mapping")
        return False

    try:
        # Serialize the domain mapping
        key = f"domain:{mapping.domain}"
        mapping_data = mapping.model_dump_json()

        # Store in Redis with TTL
        await redis_client.set(key, mapping_data, ex=REDIS_DOMAIN_TTL)

        # Update local cache
        domain_mappings[mapping.domain] = mapping.model_dump()

        logger.info(f"Saved domain mapping for {mapping.domain}")
        return True
    except Exception as e:
        logger.error(f"Error saving domain mapping for {mapping.domain}: {e}")
        return False


async def delete_domain_mapping(domain: str) -> bool:
    """Delete a domain mapping from Redis."""
    if not redis_client:
        logger.warning("Redis not available, cannot delete domain mapping")
        return False

    try:
        # Delete from Redis
        key = f"domain:{domain}"
        await redis_client.delete(key)

        # Remove from local cache
        if domain in domain_mappings:
            del domain_mappings[domain]

        logger.info(f"Deleted domain mapping for {domain}")
        return True
    except Exception as e:
        logger.error(f"Error deleting domain mapping for {domain}: {e}")
        return False


async def get_domain_backend(request: Request) -> Tuple[str, str]:
    """
    Determine which backend to route to based on domain and path.

    Args:
        request: The FastAPI request object

    Returns:
        A tuple of (backend_type, backend_url)
    """
    # Get the host from the request
    host = request.headers.get("host", "").split(":")[0]
    path = request.url.path

    # Check if we have a mapping for this domain
    mapping = domain_mappings.get(host)
    if mapping and mapping.get("enabled", True):
        backend_type = mapping.get("backend_type", "main")
        if backend_type in backend_health and backend_health[backend_type]["healthy"]:
            # Use the mapping's backend if it's healthy
            if backend_type == "main":
                return (backend_type, ENTERPRISE_MCP_SERVER_URL)

    # Fall back to path-based routing if no domain mapping or specified backend is unhealthy
    return get_target_backend(path)


async def check_rate_limit(request: Request) -> Tuple[bool, Optional[int]]:
    """
    Check if the request exceeds rate limits.

    Args:
        request: The FastAPI request object

    Returns:
        A tuple of (is_allowed, retry_after_seconds)
    """
    if not redis_client:
        logger.warning("Redis not available, skipping rate limit check")
        return (True, None)

    try:
        # Get the host and client IP
        host = request.headers.get("host", "").split(":")[0]
        client_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else "unknown"
        )

        # Get the rate limit for this domain
        mapping = domain_mappings.get(host)
        rate_limit = (
            mapping.get("rate_limit", DEFAULT_RATE_LIMIT)
            if mapping
            else DEFAULT_RATE_LIMIT
        )

        # Create a rate limit key that includes the minute
        minute = int(time.time() // 60)
        rate_key = f"ratelimit:{host}:{client_ip}:{minute}"

        # Increment the counter and set expiry
        count = await redis_client.incr(rate_key)
        await redis_client.expire(rate_key, 120)  # 2 minutes expiry to ensure cleanup

        # Check if limit exceeded
        if count > rate_limit:
            logger.warning(
                f"Rate limit exceeded for {client_ip} on {host}: {count}/{rate_limit}"
            )
            # Calculate seconds until next minute
            retry_after = 60 - (int(time.time()) % 60)
            return (False, retry_after)

        return (True, None)
    except Exception as e:
        logger.error(f"Error checking rate limit: {e}")
        # On error, allow the request
        return (True, None)


async def log_request_analytics(
    request: Request, response_status: int, response_time: float
):
    """
    Log request analytics data to Redis.

    Args:
        request: The FastAPI request object
        response_status: HTTP status code of the response
        response_time: Response time in seconds
    """
    if not redis_client:
        return

    try:
        # Get request details
        host = request.headers.get("host", "").split(":")[0]
        client_ip = request.headers.get(
            "x-forwarded-for", request.client.host if request.client else "unknown"
        )
        method = request.method
        path = request.url.path
        timestamp = datetime.now().isoformat()
        request_id = str(uuid7())

        # Create analytics entry
        analytics_data = {
            "request_id": request_id,
            "timestamp": timestamp,
            "domain": host,
            "client_ip": client_ip,
            "method": method,
            "path": path,
            "status_code": response_status,
            "response_time": response_time,
            # Add user info if available
            "user_id": request.headers.get("x-user-id", None),
        }

        # Store detailed entry with short TTL
        detail_key = f"analytics:detail:{request_id}"
        await redis_client.set(
            detail_key, json.dumps(analytics_data), ex=REDIS_ANALYTICS_TTL
        )

        # Increment counter for this domain and day
        day = datetime.now().strftime("%Y-%m-%d")
        count_key = f"analytics:count:{host}:{day}"
        await redis_client.incr(count_key)
        await redis_client.expire(count_key, REDIS_ANALYTICS_TTL)

        # Track request pattern (domain, method, path, status)
        pattern_key = f"analytics:pattern:{host}:{method}:{path.replace('/', '_')}:{response_status}:{day}"
        await redis_client.incr(pattern_key)
        await redis_client.expire(pattern_key, REDIS_ANALYTICS_TTL)

        logger.debug(f"Logged analytics for request {request_id}")
    except Exception as e:
        logger.error(f"Error logging analytics: {e}")


async def health_check_task():
    """Background task to periodically check the health of backend servers."""
    while True:
        try:
            await asyncio.gather(
                check_backend_health("main", ENTERPRISE_MCP_SERVER_URL)
            )
        except Exception as e:
            logger.error(f"Error in health check task: {e}")

        # Sleep before next check
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)


# Determine which backend to route to based on request path
def get_target_backend(path: str) -> Tuple[str, str]:
    """
    Determine which backend to route to based on request path.

    Args:
        path: The request path

    Returns:
        A tuple of (backend_type, backend_url)
    """

    # Default to main backend
    return ("main", ENTERPRISE_MCP_SERVER_URL)


# Main proxy handler
@app.api_route(
    "/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"]
)
async def proxy_request(request: Request, path: str):
    """
    Universal route that proxies requests to the appropriate backend service.

    Args:
        request: The FastAPI request object
        path: The request path

    Returns:
        The response from the backend service
    """
    # Start timing the request
    start_time = time.time()

    # Check rate limit
    allowed, retry_after = await check_rate_limit(request)
    if not allowed:
        # Return 429 Too Many Requests
        response = JSONResponse(
            status_code=429,
            content={
                "error": "Rate limit exceeded",
                "message": "Too many requests, please try again later",
                "retry_after": retry_after,
            },
            headers={"Retry-After": str(retry_after)},
        )
        # Log the rate-limited request
        await log_request_analytics(request, 429, time.time() - start_time)
        return response

    # Determine target backend based on domain and path
    backend_type, target_url = await get_domain_backend(request)

    # Check if the target backend is healthy
    if not backend_health[backend_type]["healthy"]:
        # Try to refresh the health status if it's been a while
        if (
            time.time() - backend_health[backend_type]["last_checked"]
            > HEALTH_CHECK_INTERVAL
        ):
            healthy = await check_backend_health(backend_type, target_url)
            if not healthy:
                # Still unhealthy, return error
                response = JSONResponse(
                    status_code=503,
                    content={
                        "error": "Service Unavailable",
                        "message": f"The {backend_type} backend service is currently unavailable",
                        "details": backend_health[backend_type]["error"],
                    },
                )
                # Log the failed request
                await log_request_analytics(request, 503, time.time() - start_time)
                return response

    # Construct the target URL
    target_url = f"{target_url}/{path}"

    # Get request body and headers
    body = await request.body()
    headers = dict(request.headers)

    # Remove headers that shouldn't be forwarded
    headers_to_remove = ["host", "content-length", "connection"]
    for header in headers_to_remove:
        if header in headers:
            del headers[header]

    # Add gateway identification
    headers["x-forwarded-by"] = "mcp-api-gateway"
    headers["x-forwarded-for"] = request.client.host if request.client else "unknown"

    # Add custom headers from domain mapping if available
    host = request.headers.get("host", "").split(":")[0]
    mapping = domain_mappings.get(host)
    if mapping and "custom_headers" in mapping:
        for key, value in mapping["custom_headers"].items():
            headers[key] = value

    # Forward the request to the target backend
    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(
                method=request.method,
                url=target_url,
                content=body,
                headers=headers,
                params=request.query_params,
                cookies=request.cookies,
                follow_redirects=True,
                timeout=60.0,  # Longer timeout for potentially long-running operations
            )

            # Calculate response time
            response_time = time.time() - start_time

            # Log analytics
            await log_request_analytics(request, response.status_code, response_time)

            # Prepare the response headers
            response_headers = dict(response.headers)

            # For SSE connections, we need to handle streaming
            if "text/event-stream" in response.headers.get("content-type", ""):

                async def stream_response():
                    async for chunk in response.aiter_bytes():
                        yield chunk

                return StreamingResponse(
                    stream_response(),
                    status_code=response.status_code,
                    headers=response_headers,
                    media_type="text/event-stream",
                )

            # For normal responses, return content directly
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=response_headers,
                media_type=response.headers.get("content-type"),
            )

    except httpx.RequestError as e:
        logger.error(f"Error forwarding request to {target_url}: {e}")
        response_time = time.time() - start_time
        await log_request_analytics(request, 503, response_time)
        return JSONResponse(
            status_code=503,
            content={
                "error": "Service Unavailable",
                "message": f"Error connecting to the {backend_type} backend service",
                "details": str(e),
            },
        )
    except Exception as e:
        logger.error(f"Unexpected error proxying request: {e}")
        response_time = time.time() - start_time
        await log_request_analytics(request, 500, response_time)
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal Server Error",
                "message": "An unexpected error occurred processing your request",
                "details": str(e),
            },
        )


# Health check endpoint for the gateway itself
@app.get("/health", summary="Gateway Health Check")
async def gateway_health():
    """Health check endpoint for the gateway itself."""
    return {
        "status": "healthy",
        "backends": {
            "main": {
                "url": ENTERPRISE_MCP_SERVER_URL,
                "healthy": backend_health["main"]["healthy"],
                "last_checked": backend_health["main"]["last_checked"],
            }
        },
    }


# Admin API endpoints for domain management


@app.post("/api/admin/domains", summary="Create Domain Mapping")
async def create_domain_mapping(mapping: DomainMapping):
    """
    Create or update a domain mapping.

    Args:
        mapping: The domain mapping configuration

    Returns:
        JSON response with the operation status
    """
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Redis is not available for domain mapping storage",
            },
        )

    # Validate backend type
    if mapping.backend_type not in ["main", "dynamic", "readonly"]:
        return JSONResponse(
            status_code=400,
            content={
                "status": "error",
                "message": f"Invalid backend_type: {mapping.backend_type}. Must be one of: main, dynamic, readonly",
            },
        )

    # Save the mapping
    success = await save_domain_mapping(mapping)
    if not success:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to save domain mapping"},
        )

    return JSONResponse(
        status_code=201,
        content={
            "status": "success",
            "message": f"Domain mapping for {mapping.domain} created successfully",
        },
    )


@app.get("/api/admin/domains", summary="List Domain Mappings")
async def list_domain_mappings():
    """
    List all domain mappings.

    Returns:
        JSON response with the list of domain mappings
    """
    # Refresh from Redis first
    await load_domain_mappings()

    # Convert to list for response
    mappings_list = [
        {"domain": domain, **mapping} for domain, mapping in domain_mappings.items()
    ]

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "mappings": mappings_list,
            "count": len(mappings_list),
        },
    )


@app.get("/api/admin/domains/{domain}", summary="Get Domain Mapping")
async def get_domain_mapping(domain: str):
    """
    Get a specific domain mapping.

    Args:
        domain: The domain name to retrieve

    Returns:
        JSON response with the domain mapping details
    """
    # Refresh from Redis first
    await load_domain_mappings()

    if domain not in domain_mappings:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": f"Domain mapping for {domain} not found",
            },
        )

    return JSONResponse(
        status_code=200,
        content={"status": "success", "mapping": domain_mappings[domain]},
    )


@app.delete("/api/admin/domains/{domain}", summary="Delete Domain Mapping")
async def delete_domain_mapping_endpoint(domain: str):
    """
    Delete a domain mapping.

    Args:
        domain: The domain name to delete

    Returns:
        JSON response with the operation status
    """
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Redis is not available for domain mapping storage",
            },
        )

    if domain not in domain_mappings:
        return JSONResponse(
            status_code=404,
            content={
                "status": "error",
                "message": f"Domain mapping for {domain} not found",
            },
        )

    # Delete the mapping
    success = await delete_domain_mapping(domain)
    if not success:
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": "Failed to delete domain mapping"},
        )

    return JSONResponse(
        status_code=200,
        content={
            "status": "success",
            "message": f"Domain mapping for {domain} deleted successfully",
        },
    )


# Admin API endpoints for analytics


@app.get("/api/admin/analytics/summary", summary="Get Analytics Summary")
async def get_analytics_summary(days: int = Query(7, ge=1, le=30)):
    """
    Get a summary of request analytics for the specified number of days.

    Args:
        days: Number of days to include in the summary (default: 7)

    Returns:
        JSON response with the analytics summary
    """
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Redis is not available for analytics",
            },
        )

    try:
        summary = {}
        total_requests = 0

        # Get data for each day
        for day_offset in range(days):
            day_date = (datetime.now() - timedelta(days=day_offset)).strftime(
                "%Y-%m-%d"
            )
            day_summary = {"date": day_date, "total": 0, "domains": {}}

            # Get counts for all domains for this day
            count_keys = await redis_client.keys(f"analytics:count:*:{day_date}")

            for key in count_keys:
                parts = key.split(":")
                domain = parts[2]
                count = int(await redis_client.get(key) or 0)

                day_summary["domains"][domain] = count
                day_summary["total"] += count
                total_requests += count

            summary[day_date] = day_summary

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "total_days": days,
                "total_requests": total_requests,
                "daily_summary": summary,
            },
        )
    except Exception as e:
        logger.error(f"Error getting analytics summary: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error getting analytics summary: {str(e)}",
            },
        )


@app.get("/api/admin/analytics/patterns", summary="Get Request Patterns")
async def get_request_patterns(
    domain: Optional[str] = None,
    days: int = Query(1, ge=1, le=7),
    limit: int = Query(20, ge=5, le=100),
):
    """
    Get most common request patterns (method + path combinations).

    Args:
        domain: Optional domain filter
        days: Number of days to include (default: 1)
        limit: Maximum number of patterns to return (default: 20)

    Returns:
        JSON response with the request patterns
    """
    if not redis_client:
        return JSONResponse(
            status_code=503,
            content={
                "status": "error",
                "message": "Redis is not available for analytics",
            },
        )

    try:
        patterns = []

        # Get data for each day
        for day_offset in range(days):
            day_date = (datetime.now() - timedelta(days=day_offset)).strftime(
                "%Y-%m-%d"
            )

            # Get pattern keys for this day
            pattern_prefix = (
                f"analytics:pattern:{domain}:" if domain else "analytics:pattern:"
            )
            pattern_keys = await redis_client.keys(f"{pattern_prefix}*:{day_date}")

            # Get counts and parse patterns
            for key in pattern_keys:
                count = int(await redis_client.get(key) or 0)

                # Parse the key parts: analytics:pattern:domain:method:path:status:date
                parts = key.split(":")
                if len(parts) >= 7:  # Ensure we have enough parts
                    pattern_domain = parts[2]
                    method = parts[3]
                    path = parts[4].replace("_", "/")
                    status = parts[5]

                    patterns.append(
                        {
                            "domain": pattern_domain,
                            "method": method,
                            "path": path,
                            "status": status,
                            "count": count,
                            "date": day_date,
                        }
                    )

        # Sort patterns by count (descending) and limit results
        patterns.sort(key=lambda x: x["count"], reverse=True)
        patterns = patterns[:limit]

        return JSONResponse(
            status_code=200,
            content={
                "status": "success",
                "patterns": patterns,
                "count": len(patterns),
                "days": days,
            },
        )
    except Exception as e:
        logger.error(f"Error getting request patterns: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": f"Error getting request patterns: {str(e)}",
            },
        )


# Startup event to initialize health checks
@app.on_event("startup")
async def startup_event():
    """Initialize backend health checks on startup."""
    logger.info("API Gateway starting up")
    logger.info(f"Main MCP URL: {ENTERPRISE_MCP_SERVER_URL}")

    # Initial health checks
    await asyncio.gather(check_backend_health("main", ENTERPRISE_MCP_SERVER_URL))

    # Load domain mappings from Redis
    await load_domain_mappings()

    # Start background health check task
    asyncio.create_task(health_check_task())


if __name__ == "__main__":
    import uvicorn

    logger.info(f"Starting API Gateway on {GATEWAY_HOST}:{GATEWAY_PORT}")
    uvicorn.run(
        "api_gateway:app", host=GATEWAY_HOST, port=GATEWAY_PORT, log_level="info"
    )
