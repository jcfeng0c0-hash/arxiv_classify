#!/bin/bash
# Quick Start Script
# Quick Start Script for ArXiv WebUI

echo "================================================"
echo "📱 ArXiv Paper Database - Mobile WebUI"
echo "================================================"
echo ""

# Check current directory
if [ ! -f "webui.py" ]; then
    echo "❌ Error: please run this script from the project root"
    echo "   cd /path/to/arxiv_classify-2.0.0-public"
    exit 1
fi

echo "✅ Project directory confirmed"
echo ""

# Get IP address
echo "📡 Retrieving server IP address..."
echo ""
if command -v hostname &> /dev/null; then
    IPS=$(hostname -I 2>/dev/null || hostname -i 2>/dev/null)
    if [ -n "$IPS" ]; then
        echo "🌐 Your IP addresses:"
        for IP in $IPS; do
            if [[ $IP != 127.0.0.1 ]]; then
                echo "   http://$IP:5000"
            fi
        done
    fi
fi
echo ""

# Show usage instructions
echo "📱 Mobile access steps:"
echo "   1. Make sure your phone and server are on the same WiFi"
echo "   2. Enter the address above in your phone's browser"
echo "   3. Start using!"
echo ""

echo "🖥️  Desktop access:"
echo "   http://localhost:5000"
echo ""

echo "================================================"
echo "🚀 Starting WebUI service..."
echo "================================================"
echo ""
echo "💡 Tips:"
echo "   - Press Ctrl+C to stop the service"
echo "   - Logs will appear below"
echo "   - First load may take a few seconds"
echo ""
echo "================================================"
echo ""

# Start the service
python3 webui.py
