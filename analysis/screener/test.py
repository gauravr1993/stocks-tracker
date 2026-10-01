import sys
import os

# Walk up until we find the project root (contains 'analysis' folder)
root = os.path.abspath('..')
while not os.path.exists(os.path.join(root, 'analysis')):
    root = os.path.dirname(root)
if root not in sys.path:
    sys.path.insert(0, root)

print(f"Project root: {root}")  # confirm it found the right folder

from dotenv import load_dotenv
import os

# Load .env relative to project root, not notebook location
load_dotenv(os.path.join(root, 'config', '.env'))

# Verify it loaded
import os
print("SUPABASE_URL set:", bool(os.environ.get("SUPABASE_URL")))

from analysis.screener.run_screener import run_screener, get_picks, sector_summary
df = run_screener()
# 1. Score distributions — should be spread across 0–100, not bunched
print(df[['value_score','momentum_score','sector_score','composite_score']].describe())

# 2. Check high conviction picks make intuitive sense
high_conviction = get_picks(df, n=5, mode='balanced')
print(high_conviction[['symbol','sector','composite_score','pe_ratio','return_1y']])

# 3. Sector leaderboard — does it match your own market read?
print(sector_summary(df)[['sector','stocks','sector_strength','median_return_1y']])

# 4. Any stocks with NaN composite? (data gaps)
print(df[df['composite_score'].isna()][['symbol','value_score','momentum_score','sector_score']])