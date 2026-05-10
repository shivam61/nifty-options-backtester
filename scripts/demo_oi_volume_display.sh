#!/bin/bash
# Quick demo of the enhanced monitor with OI/volume display

echo "═══════════════════════════════════════════════════════════"
echo "  ENHANCED MONITOR DEMO - OI & Volume Display"
echo "═══════════════════════════════════════════════════════════"
echo ""
echo "Running monitor to show Open Interest and Volume data..."
echo ""

cd /Users/shivam.gupta/cursor/dsp-repos/nifty-options-backtester
source .venv/bin/activate

python main.py --mode monitor

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "Demo complete!"
echo ""
echo "Features demonstrated:"
echo "  ✓ Open Interest (OI) per leg"
echo "  ✓ Volume traded per leg"
echo "  ✓ Bid-Ask spreads"
echo "  ✓ Live prices from Fyers API"
echo ""
echo "Use this data to:"
echo "  • Assess liquidity before exiting"
echo "  • Understand market sentiment (OI changes)"
echo "  • Calculate transaction costs (spreads)"
echo "  • Time your exits for best execution"
echo "═══════════════════════════════════════════════════════════"
