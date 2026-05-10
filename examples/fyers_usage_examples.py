"""
Example: Using Fyers Live Data for Options Analysis
Demonstrates practical usage of FyersLiveDataClient for options trading.
"""

from data.fyers_live_data import FyersLiveDataClient
from datetime import date, datetime, timedelta
import pandas as pd


def example_1_basic_quotes():
    """Example 1: Get basic market quotes"""
    print("\n" + "=" * 70)
    print("Example 1: Basic Market Quotes")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    # Get current market levels
    spot = client.get_nifty_spot_price()
    vix = client.get_india_vix()
    atm = client.get_atm_strike(spot)
    
    print(f"\n📊 Current Market State:")
    print(f"   NIFTY Spot: ₹{spot:,.2f}")
    print(f"   India VIX:  {vix:.2f}")
    print(f"   ATM Strike: ₹{atm:,.0f}")


def example_2_option_chain():
    """Example 2: Fetch complete option chain"""
    print("\n" + "=" * 70)
    print("Example 2: Option Chain Analysis")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    # Get strikes around ATM
    strikes = client.get_strikes_around_atm(num_strikes=3)
    
    # Next weekly expiry (example - adjust based on actual expiry calendar)
    expiry = date(2026, 4, 24)
    
    # Fetch option chain
    print(f"\n🎯 Fetching option chain for expiry: {expiry}")
    print(f"   Strikes: {strikes}")
    
    chain = client.get_option_chain_quotes(strikes, expiry)
    
    # Separate calls and puts
    calls = chain[chain['option_type'] == 'CE'].sort_values('strike')
    puts = chain[chain['option_type'] == 'PE'].sort_values('strike')
    
    print(f"\n📈 Option Chain Data:")
    print(f"\n   Calls (CE):")
    print(calls[['strike', 'ltp', 'bid', 'ask', 'volume', 'open_interest']].to_string(index=False))
    
    print(f"\n   Puts (PE):")
    print(puts[['strike', 'ltp', 'bid', 'ask', 'volume', 'open_interest']].to_string(index=False))
    
    # Calculate Put-Call Ratio
    total_ce_oi = calls['open_interest'].sum()
    total_pe_oi = puts['open_interest'].sum()
    pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 0
    
    print(f"\n   Put-Call Ratio (OI): {pcr:.2f}")


def example_3_iron_condor_setup():
    """Example 3: Find strikes for Iron Condor strategy"""
    print("\n" + "=" * 70)
    print("Example 3: Iron Condor Strike Selection")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    spot = client.get_nifty_spot_price()
    vix = client.get_india_vix()
    atm = client.get_atm_strike(spot)
    
    # Iron Condor parameters based on VIX regime
    if vix < 13:
        # Low VIX - sell closer to ATM
        call_short_distance = 150
        put_short_distance = 150
        wing_width = 50
    elif vix < 18:
        # Medium VIX
        call_short_distance = 200
        put_short_distance = 200
        wing_width = 50
    else:
        # High VIX - sell further from ATM
        call_short_distance = 300
        put_short_distance = 300
        wing_width = 100
    
    # Calculate strikes
    call_short_strike = atm + call_short_distance
    call_long_strike = call_short_strike + wing_width
    put_short_strike = atm - put_short_distance
    put_long_strike = put_short_strike - wing_width
    
    print(f"\n🎯 Iron Condor Setup (VIX={vix:.2f}):")
    print(f"   Spot: ₹{spot:,.2f} | ATM: ₹{atm:,.0f}")
    print(f"\n   Put Spread:")
    print(f"      Buy:  {put_long_strike:,.0f} PE")
    print(f"      Sell: {put_short_strike:,.0f} PE")
    print(f"\n   Call Spread:")
    print(f"      Sell: {call_short_strike:,.0f} CE")
    print(f"      Buy:  {call_long_strike:,.0f} CE")
    
    # Fetch quotes for these strikes
    expiry = date(2026, 4, 24)
    strikes = [put_long_strike, put_short_strike, call_short_strike, call_long_strike]
    
    print(f"\n💰 Fetching live premiums...")
    chain = client.get_option_chain_quotes(strikes, expiry)
    
    # Calculate strategy metrics
    put_long = chain[(chain['strike'] == put_long_strike) & (chain['option_type'] == 'PE')]
    put_short = chain[(chain['strike'] == put_short_strike) & (chain['option_type'] == 'PE')]
    call_short = chain[(chain['strike'] == call_short_strike) & (chain['option_type'] == 'CE')]
    call_long = chain[(chain['strike'] == call_long_strike) & (chain['option_type'] == 'CE')]
    
    if len(put_long) > 0 and len(put_short) > 0 and len(call_short) > 0 and len(call_long) > 0:
        # Net credit = premiums received - premiums paid
        put_spread_credit = put_short['ltp'].iloc[0] - put_long['ltp'].iloc[0]
        call_spread_credit = call_short['ltp'].iloc[0] - call_long['ltp'].iloc[0]
        total_credit = put_spread_credit + call_spread_credit
        
        # Max loss per spread
        put_spread_risk = wing_width - put_spread_credit
        call_spread_risk = wing_width - call_spread_credit
        max_loss = max(put_spread_risk, call_spread_risk)
        
        print(f"\n   Strategy P&L:")
        print(f"      Put Spread Credit:  ₹{put_spread_credit:.2f}")
        print(f"      Call Spread Credit: ₹{call_spread_credit:.2f}")
        print(f"      Total Credit:       ₹{total_credit:.2f}")
        print(f"      Max Loss:           ₹{max_loss:.2f}")
        print(f"      Risk-Reward Ratio:  {max_loss/total_credit:.2f}:1")


def example_4_live_monitoring():
    """Example 4: Live position monitoring"""
    print("\n" + "=" * 70)
    print("Example 4: Live Position Monitoring")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    # Example: You have an existing position
    # 24500 CE Short, 24550 CE Long, 24300 PE Short, 24250 PE Long
    positions = [
        {'strike': 24550, 'type': 'CE', 'qty': 1, 'entry_price': 30},
        {'strike': 24500, 'type': 'CE', 'qty': -1, 'entry_price': 65},
        {'strike': 24300, 'type': 'PE', 'qty': -1, 'entry_price': 70},
        {'strike': 24250, 'type': 'PE', 'qty': 1, 'entry_price': 35},
    ]
    
    expiry = date(2026, 4, 24)
    strikes = [p['strike'] for p in positions]
    
    print(f"\n📊 Monitoring {len(positions)} positions...")
    
    # Fetch current quotes
    chain = client.get_option_chain_quotes(strikes, expiry)
    
    # Calculate P&L
    total_pnl = 0
    print(f"\n   Position P&L:")
    
    for pos in positions:
        current_quote = chain[
            (chain['strike'] == pos['strike']) & 
            (chain['option_type'] == pos['type'])
        ]
        
        if len(current_quote) > 0:
            current_price = current_quote['ltp'].iloc[0]
            pnl = (pos['entry_price'] - current_price) * pos['qty']
            total_pnl += pnl
            
            action = "Short" if pos['qty'] < 0 else "Long"
            print(f"      {pos['strike']:,.0f} {pos['type']} {action}: "
                  f"Entry ₹{pos['entry_price']:.2f} → Current ₹{current_price:.2f} "
                  f"| P&L: ₹{pnl:.2f}")
    
    print(f"\n   Total P&L: ₹{total_pnl:.2f}")
    
    # Check current market state
    spot = client.get_nifty_spot_price()
    vix = client.get_india_vix()
    
    print(f"\n   Market State:")
    print(f"      NIFTY: ₹{spot:,.2f}")
    print(f"      VIX:   {vix:.2f}")


def example_5_historical_analysis():
    """Example 5: Historical data analysis"""
    print("\n" + "=" * 70)
    print("Example 5: Historical Data Analysis")
    print("=" * 70)
    
    client = FyersLiveDataClient()
    
    # Get historical data for NIFTY
    print(f"\n📈 Fetching 5-day historical data for NIFTY...")
    
    hist = client.get_historical_data(
        'NSE:NIFTY50-INDEX',
        resolution='D',  # Daily
        date_from=date.today() - timedelta(days=7),
        date_to=date.today()
    )
    
    if len(hist) > 0:
        print(f"\n   Last 5 Days:")
        print(hist.tail().to_string())
        
        # Calculate some metrics
        current_close = hist['close'].iloc[-1]
        prev_close = hist['close'].iloc[-2]
        daily_change = ((current_close - prev_close) / prev_close) * 100
        
        week_high = hist['high'].tail(5).max()
        week_low = hist['low'].tail(5).min()
        
        print(f"\n   Analytics:")
        print(f"      Current Close:  ₹{current_close:,.2f}")
        print(f"      Daily Change:   {daily_change:+.2f}%")
        print(f"      Week High:      ₹{week_high:,.2f}")
        print(f"      Week Low:       ₹{week_low:,.2f}")
        print(f"      Week Range:     ₹{week_high - week_low:,.2f}")


def main():
    """Run all examples"""
    print("\n" + "=" * 70)
    print("FYERS LIVE DATA - USAGE EXAMPLES")
    print("=" * 70)
    
    try:
        example_1_basic_quotes()
        example_2_option_chain()
        example_3_iron_condor_setup()
        example_4_live_monitoring()
        example_5_historical_analysis()
        
        print("\n" + "=" * 70)
        print("✓ All examples completed successfully!")
        print("=" * 70)
        
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        print("\nNote: Some examples may fail if:")
        print("1. Market is closed (no live quotes available)")
        print("2. Access token is expired")
        print("3. Specific strikes don't exist for the expiry date")


if __name__ == "__main__":
    main()
