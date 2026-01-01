#!/bin/bash

# Claude Code Integration Setup Script
# This script helps set up the complete Claude Code integration

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo "========================================="
echo "Claude Code Integration Setup"
echo "========================================="
echo ""

# Check if running from project root
if [ ! -f "$PROJECT_ROOT/docker-compose.yml" ]; then
    echo "❌ Error: Please run this script from the project root directory"
    echo "Usage: ./scripts/setup_claude_integration.sh"
    exit 1
fi

echo "🔍 Project root: $PROJECT_ROOT"
echo ""

# Step 1: Check prerequisites
echo "📋 Step 1: Checking prerequisites..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    echo "   Visit: https://docs.docker.com/get-docker/"
    exit 1
fi
echo "✅ Docker found: $(docker --version)"

# Check Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose is not available. Please install Docker Compose."
    exit 1
fi
echo "✅ Docker Compose available"

# Step 2: Environment setup
echo ""
echo "🔧 Step 2: Environment setup..."

if [ ! -f "$PROJECT_ROOT/.env" ]; then
    if [ -f "$PROJECT_ROOT/.env.example" ]; then
        echo "📝 Creating .env from .env.example..."
        cp "$PROJECT_ROOT/.env.example" "$PROJECT_ROOT/.env"
        echo "⚠️  Please edit .env file with your specific configuration"
        echo "   Key settings to update:"
        echo "   - POSTGRES_PASSWORD"
        echo "   - JWT_SECRET_KEY"
        echo "   - CLIENT_ID and CLIENT_SECRET"
        echo ""
    else
        echo "❌ No .env.example found. Please create .env file manually."
        exit 1
    fi
else
    echo "✅ .env file exists"
fi

# Step 3: Build the updated container
echo ""
echo "🏗️  Step 3: Building updated Docker container with Claude CLI..."
echo "This may take several minutes..."

if docker compose build; then
    echo "✅ Container build successful"
else
    echo "❌ Container build failed"
    echo "Check the error messages above and fix any issues"
    exit 1
fi

# Step 4: Start services
echo ""
echo "🚀 Step 4: Starting services..."

if docker compose up -d; then
    echo "✅ Services started successfully"
else
    echo "❌ Failed to start services"
    exit 1
fi

# Step 5: Wait for services to be ready
echo ""
echo "⏳ Step 5: Waiting for services to be ready..."

# Wait for the main service to be healthy
for i in {1..30}; do
    if docker compose ps | grep -q "healthy"; then
        echo "✅ Services are healthy"
        break
    elif [ $i -eq 30 ]; then
        echo "⚠️  Services taking longer than expected to start"
        echo "Check service status with: docker compose ps"
        echo "Check logs with: docker compose logs"
        break
    else
        echo "   Waiting... ($i/30)"
        sleep 2
    fi
done

# Step 6: Authentication setup instructions
echo ""
echo "🔐 Step 6: Claude Authentication Setup"
echo ""
echo "Your Enterprise MCP Server is now running with Claude Code integration!"
echo "To complete the setup, you need to authenticate with Claude:"
echo ""
echo "Method 1 - Using MCP tools (Recommended):"
echo "  1. Check auth status:"
echo "     curl -X POST http://localhost:8030/claude_auth/claude_auth_status"
echo ""
echo "  2. Perform authentication:"
echo "     curl -X POST http://localhost:8030/claude_auth/claude_auth_login \\"
echo "       -H 'Content-Type: application/json' \\"
echo "       -d '{\"browser_auth\": true}'"
echo ""
echo "Method 2 - Manual authentication:"
echo "  1. Enter the container:"
echo "     docker exec -it enterprise-mcp-server bash"
echo ""
echo "  2. Run authentication:"
echo "     claude login"
echo ""
echo "Method 3 - Use the setup script:"
echo "  docker exec -it enterprise-mcp-server ./scripts/claude_auth_setup.sh"
echo ""

# Step 7: Service information
echo ""
echo "📊 Step 7: Service Information"
echo ""
echo "Services are running at:"
echo "  • Main MCP Server: http://localhost:8030"
echo "  • API Documentation: http://localhost:8030/docs"
echo "  • Health Check: http://localhost:8030/api/health"
echo ""
echo "Available tools after authentication:"
echo "  • claude_code - Execute Claude Code CLI"
echo "  • claude_health - Test Claude CLI functionality"
echo "  • claude_auth_status - Check authentication status"
echo "  • claude_auth_login - Perform authentication"
echo "  • claude_auth_test - Test authentication"
echo ""

# Step 8: Next steps
echo "🎯 Next Steps:"
echo ""
echo "1. Complete Claude authentication (see methods above)"
echo "2. Test the integration:"
echo "   docker exec enterprise-mcp-server claude --version"
echo ""
echo "3. Configure your MCP client (e.g., Cursor) to connect to:"
echo "   http://localhost:8030/sse"
echo ""
echo "4. Check logs if you encounter issues:"
echo "   docker compose logs -f enterprise-mcp-server"
echo ""
echo "📚 For detailed setup instructions, see:"
echo "   docs/claude_setup.md"
echo ""

# Final status check
echo "🔍 Current Status:"
docker compose ps

echo ""
echo "========================================="
echo "Setup completed! 🎉"
echo "========================================="

# Offer to run authentication setup
echo ""
read -p "Would you like to run Claude authentication now? (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Starting Claude authentication..."
    docker exec -it enterprise-mcp-server ./scripts/claude_auth_setup.sh
fi

echo ""
echo "Setup script finished. Happy coding! 👨‍💻"