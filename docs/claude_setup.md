# Claude Code CLI Setup and Authentication Guide

This guide walks you through setting up the Claude Code CLI integration in the Enterprise MCP Server, including authentication via browser-based OAuth.

## Overview

The Claude Code CLI integration provides access to Claude's coding capabilities through the official `@anthropic-ai/claude-code` CLI tool. This allows you to:

- Generate and modify code using Claude
- Analyze existing codebases
- Get coding assistance with context awareness
- Use Claude's tools (Read, Write, Bash) in a controlled environment

## Prerequisites

- Docker and Docker Compose (for containerized deployment)
- Node.js 20+ and npm (for local development)
- Internet connection for authentication
- Browser access for OAuth flow

## Installation and Setup

### 1. Container Setup (Recommended)

The Docker setup automatically installs all required dependencies:

```bash
# Build the updated container with Claude CLI support
docker compose build

# Start the services
docker compose up -d
```

### 2. Local Development Setup

For local development without Docker:

```bash
# Install Node.js dependencies
npm install -g @anthropic-ai/claude-code

# Install Python dependencies (claude-code-sdk should be in requirements.txt)
pip install claude-code-sdk

# Verify installation
claude --version
```

## Authentication Setup

### Method 1: Using MCP Authentication Tools (Recommended)

The server provides built-in tools for managing Claude authentication:

#### Check Authentication Status
```bash
# Call the claude_auth_status tool to check current status
curl -X POST http://localhost:8030/tools/claude_auth/claude_auth_status
```

#### Perform Authentication
```bash
# Use the claude_auth_login tool for interactive authentication
curl -X POST http://localhost:8030/tools/claude_auth/claude_auth_login \
  -H "Content-Type: application/json" \
  -d '{"browser_auth": true}'
```

#### Test Authentication
```bash
# Test if authentication is working
curl -X POST http://localhost:8030/tools/claude_auth/claude_auth_test
```

### Method 2: Manual Authentication

#### In Docker Container
```bash
# Enter the running container
docker exec -it enterprise-mcp-server bash

# Run the authentication setup script
./scripts/claude_auth_setup.sh

# Or use Claude CLI directly
claude login
```

#### On Host System
```bash
# Run authentication setup script
./scripts/claude_auth_setup.sh

# Or use Claude CLI directly
claude login
```

## Authentication Flow Details

### Browser-Based OAuth (Default)

1. **Initiation**: Run `claude login` or use `claude_auth_login` tool
2. **Browser Launch**: A browser window opens to Claude's authentication page
3. **Login**: Sign in with your Claude account (requires Claude subscription)
4. **Authorization**: Grant permissions to the CLI application
5. **Callback**: Authentication token is saved to `~/.claude/config.json`
6. **Persistence**: In Docker, this is stored in the `claude_auth` volume

### Headless/Container Environment

For headless environments (like Docker containers):

1. **URL Generation**: Authentication URL is displayed in terminal
2. **Manual Browser**: Copy URL and open in browser on host machine
3. **Completion**: Container detects when authentication is complete
4. **Storage**: Credentials stored in persistent volume

## Configuration Files

### Authentication Config
- **Location**: `~/.claude/config.json` (or `$HOME/.claude/config.json`)
- **Docker Volume**: `claude_auth:/root/.claude`
- **Format**:
```json
{
  "api_key": "your-api-key-or-token",
  "auth_method": "oauth",
  "profile": "default",
  "token": "oauth-access-token",
  "refresh_token": "oauth-refresh-token"
}
```

### Environment Variables
Add these to your `.env` file if needed:

```bash
# Claude-specific configuration
CLAUDE_CONFIG_PATH=/root/.claude
CLAUDE_AUTH_METHOD=oauth
CLAUDE_CLI_TIMEOUT=300

# Optional: API key auth (if supported)
CLAUDE_API_KEY=your-api-key-here
```

## Usage Examples

### Basic Code Generation
```python
# Using the claude_code tool
response = await claude_code(
    prompt="Create a Python function to calculate fibonacci numbers",
    allowed_tools=["Write"],
    permission_mode="acceptEdits"
)
```

### Code Analysis
```python
# Analyze existing code
response = await claude_code(
    prompt="Analyze this codebase for security vulnerabilities",
    path="/app/src",
    allowed_tools=["Read", "Grep"],
    permission_mode="plan"
)
```

### Interactive Development
```python
# Multi-turn conversation for complex tasks
response = await claude_code(
    prompt="Help me refactor this module to use async/await",
    system_prompt="You are an expert Python developer",
    allowed_tools=["Read", "Write", "Bash"],
    permission_mode="acceptEdits",
    max_turns=5
)
```

## Troubleshooting

### Common Issues

#### Authentication Failures
```bash
# Check if CLI is installed
which claude

# Check authentication status
claude_auth_status

# Re-authenticate if needed
claude_auth_login

# Manual re-authentication
claude login --force
```

#### Permission Errors
```bash
# Check file permissions
ls -la ~/.claude/

# Fix permissions if needed
chmod 600 ~/.claude/config.json
```

#### Network/Connectivity Issues
```bash
# Test network connectivity
curl -I https://claude.ai

# Check for proxy settings
echo $HTTP_PROXY $HTTPS_PROXY

# Test authentication with minimal request
claude_auth_test
```

#### Docker Volume Issues
```bash
# Check if volume exists
docker volume ls | grep claude_auth

# Inspect volume
docker volume inspect claude_auth

# Remove and recreate if corrupted
docker volume rm claude_auth
docker compose up -d
```

### Error Messages and Solutions

#### "Claude Code CLI not found"
**Solution**: Rebuild Docker container or install CLI locally
```bash
# Docker
docker compose build --no-cache

# Local
npm install -g @anthropic-ai/claude-code
```

#### "Authentication required"
**Solution**: Complete authentication flow
```bash
# Use authentication tools
claude_auth_login

# Or manual
claude login
```

#### "Permission denied"
**Solution**: Check file permissions and Docker volumes
```bash
# Fix permissions
chmod -R 755 ~/.claude
chmod 600 ~/.claude/config.json

# Check Docker volume mount
docker inspect enterprise-mcp-server | grep claude_auth
```

#### "Timeout error"
**Solution**: Increase timeouts or check network
```bash
# Set environment variable
export CLAUDE_CLI_TIMEOUT=600

# Check network connectivity
ping claude.ai
```

## Security Considerations

### Credential Storage
- Authentication tokens are stored locally in `~/.claude/config.json`
- In Docker, credentials persist in named volumes
- Tokens have expiration dates and may need refresh

### Network Security
- Authentication requires HTTPS connection to Claude servers
- OAuth flow uses secure redirect URLs
- No credentials are logged or exposed in plain text

### Access Control
- Tools respect permission modes (`plan`, `acceptEdits`, `bypassPermissions`)
- File system access is limited by allowed tools
- Commands run with container user privileges

## Advanced Configuration

### Custom Authentication Server
For enterprise environments, you can configure custom OAuth endpoints:

```python
# In claude_auth.py, modify the auth_url generation
auth_url = f"https://your-claude-proxy.com/auth?callback={callback_url}"
```

### API Key Authentication
If API key auth is supported:

```bash
# Set API key directly
claude_auth_login --api_key YOUR_API_KEY

# Or via environment
export CLAUDE_API_KEY=your-api-key
```

### Batch Authentication
For multiple containers or automated deployments:

```bash
# Copy authentication from authenticated host
docker cp ~/.claude enterprise-mcp-server:/root/

# Or use shared volume
docker run -v ~/.claude:/root/.claude ...
```

## Monitoring and Maintenance

### Health Checks
```bash
# Regular health check
claude_health

# Detailed status
claude_auth_status

# Test functionality
claude_auth_test
```

### Log Monitoring
```bash
# Container logs
docker logs enterprise-mcp-server

# Authentication-specific logs
docker logs enterprise-mcp-server | grep -i "claude\|auth"
```

### Token Refresh
Authentication tokens may expire. The system should automatically handle refresh, but manual renewal may be needed:

```bash
# Force re-authentication
claude login --force

# Or via tool
claude_auth_login --force
```

## Support and Documentation

- **Claude Code Documentation**: Check official Anthropic documentation
- **Issues**: Report problems to the enterprise MCP server repository
- **Logs**: Include container logs when reporting issues
- **Configuration**: Share sanitized config files (remove secrets)

## Changelog

- **v1.1**: Added Node.js and Claude CLI to Docker image
- **v1.1**: Implemented authentication management tools
- **v1.1**: Added persistent volume for authentication
- **v1.1**: Enhanced error handling and user feedback