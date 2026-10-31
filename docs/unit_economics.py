"""Unit-economics model behind docs/BUSINESS_PLAN.md.

Run: python3 docs/unit_economics.py

Every input is an assumption, listed at the top. Replace the token counts
with measured values from /api/admin/costs once the new pipeline ships, and
replace FIXED_MONTHLY with real invoices.
"""

M = 1_000_000

# --- Model prices, USD per 1M tokens: (input, output, cache read, 5-min cache write)
SONNET_5 = (2.00, 10.00, 0.20, 2.50)
SONNET_5_5 = (2.00, 10.00, 0.20, 2.50)
OPUS_5_5 = (4.00, 20.00, 0.20, 5.00)
HAIKU_5_5 = (0.10, 0.50, 0.01, 0.125)

# --- Payment + ops assumptions
STRIPE_PCT = 0.029
STRIPE_FIXED = 0.30
GATEWAY_FEE = 0.055          # OpenRouter-style credit purchase fee (current setup)
FIXED_MONTHLY = 65.0         # Vercel Pro + Neon + domain + misc (est., verify)
INFRA_VAR_PER_MSG = 0.001    # function time, DB writes, bandwidth (est.)
FREE_SHARE = 0.15            # free messages as a share of paid messages
LOSS_BUFFER = 0.03           # refunds, disputes, failed generations
TARGET_MARGIN = 0.04
CACHE_WARM_RATE = 0.70       # share of generations that hit a warm system-prompt cache


def cost(p, uncached=0, cache_read=0, cache_write=0, out=0):
    pin, pout, pread, pwrite = p
    return (uncached * pin + cache_read * pread + cache_write * pwrite + out * pout) / M


def current_pipeline():
    """Today: Jev + halachic + moral (+20% reconsideration) + voice, no caching."""
    halachic = cost(SONNET_5, uncached=3500, out=900)
    moral = cost(SONNET_5, uncached=2500, out=400)
    voice = cost(SONNET_5, uncached=4000, out=800)
    return 0.0001 + halachic + moral + 0.2 * halachic + voice


def new_pipeline(gen_model=SONNET_5_5):
    """Proposed: Haiku guard + one cached generation call + async Haiku audit."""
    guard = cost(HAIKU_5_5, uncached=300, cache_read=900, out=120)
    audit = cost(HAIKU_5_5, uncached=1500, cache_read=900, out=80)
    # ~3.5k-token cached constitution, ~1.5k history (half cached), ~2k RAG + message uncached,
    # ~700 visible output + ~200 thinking at low effort.
    warm = cost(gen_model, uncached=2100, cache_read=3500 + 750, cache_write=750, out=900)
    cold = cost(gen_model, uncached=2100, cache_write=3500 + 1500, out=900)
    gen = CACHE_WARM_RATE * warm + (1 - CACHE_WARM_RATE) * cold
    return guard + audit + gen


def loaded_cost(volume, gen_model=SONNET_5_5):
    variable = new_pipeline(gen_model) + INFRA_VAR_PER_MSG
    return (variable + FIXED_MONTHLY / volume + FREE_SHARE * variable) * (1 + LOSS_BUFFER)


def pack_margin(credits, price, per_msg_cost):
    net = price * (1 - STRIPE_PCT) - STRIPE_FIXED
    return (net - credits * per_msg_cost) / (credits * per_msg_cost)


def max_credits(price, per_msg_cost, margin=TARGET_MARGIN):
    return (price * (1 - STRIPE_PCT) - STRIPE_FIXED) / (per_msg_cost * (1 + margin))


if __name__ == "__main__":
    cur = current_pipeline()
    print(f"Current pipeline LLM cost/msg:          ${cur:.4f}  (with gateway fee ${cur * (1 + GATEWAY_FEE):.4f})")
    print(f"Proposed pipeline (Sonnet 5.5) cost/msg: ${new_pipeline():.4f}")
    print(f"Proposed pipeline (Opus 5.5) cost/msg:   ${new_pipeline(OPUS_5_5):.4f}")
    print()
    for vol in (5_000, 15_000, 25_000, 100_000):
        print(f"Fully loaded cost/msg at {vol:>7,} msgs/mo: ${loaded_cost(vol):.4f}")
    print()
    base = loaded_cost(25_000)
    print("Max credits per price at 4% margin (25k msgs/mo):")
    for price in (2, 5, 12, 25):
        print(f"  ${price:>2}: {max_credits(price, base):6.1f} credits")
    print()
    print("Recommended packs, margin by monthly volume:")
    for credits, price in ((55, 2), (160, 5), (400, 12)):
        cells = "  ".join(
            f"{vol // 1000}k: {pack_margin(credits, price, loaded_cost(vol)) * 100:6.1f}%"
            for vol in (5_000, 15_000, 25_000, 100_000)
        )
        print(f"  {credits:>3} credits / ${price:>2} (${price / credits:.4f}/msg)  {cells}")
    print()
    print("Current packs vs current cost (free tier and TTS excluded):")
    for credits, price in ((10, 1.00), (25, 2.00)):
        net = price * (1 - STRIPE_PCT) - STRIPE_FIXED
        c = credits * cur * (1 + GATEWAY_FEE)
        print(f"  {credits} for ${price:.2f}: net ${net:.2f}, LLM ${c:.2f}, margin {(net - c) / c * 100:.0f}%")
