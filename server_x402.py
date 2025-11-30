#!/usr/bin/env python3
"""
x402 Seller Server - Following official docs exactly.

This is a standard HTTP server with x402 payment middleware.
Later we'll adapt this for audio transport.
"""

import os
from typing import Any, Dict
from dotenv import load_dotenv
from fastapi import FastAPI
from x402.fastapi.middleware import require_payment

# Load environment variables
load_dotenv()

# Get seller address from env
SELLER_ADDRESS = os.getenv("SELLER_ADDRESS", "0x0000000000000000000000000000000000000000")

app = FastAPI(title="x402 Audio Demo - Seller")

# Apply payment middleware to the /resource endpoint
# Using testnet facilitator: https://x402.org/facilitator
app.middleware("http")(
    require_payment(
        path="/resource",
        price="$0.001",  # $0.001 USDC
        pay_to_address=SELLER_ADDRESS,
        network="base-sepolia",
        description="Access to protected audio resource",
    )
)


@app.get("/")
async def root():
    """Health check endpoint (not protected)."""
    return {"status": "ok", "message": "x402 Audio Demo Server"}


@app.get("/resource")
async def get_resource() -> Dict[str, Any]:
    """Protected resource - requires payment."""
    return {
        "message": "ACCESS GRANTED!",
        "secret": "The password is 'audio-payment-works'",
        "data": "This content was paid for via x402"
    }


if __name__ == "__main__":
    import uvicorn
    print(f"Starting x402 server...")
    print(f"Seller address: {SELLER_ADDRESS}")
    print(f"Network: base-sepolia")
    print(f"Price: $0.001 USDC")
    print(f"\nTest with: curl http://localhost:4021/resource")
    uvicorn.run(app, host="0.0.0.0", port=4021)

