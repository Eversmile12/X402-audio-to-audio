"""
EIP-3009 Facilitator - settles transferWithAuthorization on-chain.
"""

import os
from dotenv import load_dotenv
from web3 import Web3
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from config import BASE_SEPOLIA_RPC, get_usdc_address, DEFAULT_NETWORK

load_dotenv()

# Facilitator wallet (needs ETH for gas)
FACILITATOR_PRIVATE_KEY = os.getenv("FACILITATOR_PRIVATE_KEY", "")

# USDC address
USDC_ADDRESS = get_usdc_address(DEFAULT_NETWORK)

# ABI for transferWithAuthorization
TRANSFER_AUTH_ABI = [
    {
        "inputs": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
            {"name": "v", "type": "uint8"},
            {"name": "r", "type": "bytes32"},
            {"name": "s", "type": "bytes32"}
        ],
        "name": "transferWithAuthorization",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]


class SettlementRequest(BaseModel):
    """EIP-3009 authorization parameters."""
    from_address: str  # 'from' is reserved in Python
    to: str
    value: int
    valid_after: int
    valid_before: int
    nonce: str  # 32-byte hex string (0x...)
    v: int
    r: str  # 32-byte hex string (0x...)
    s: str  # 32-byte hex string (0x...)


def get_web3() -> Web3:
    """Create Web3 connection to Base Sepolia."""
    w3 = Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))
    if not w3.is_connected():
        raise RuntimeError("Failed to connect to Base Sepolia")
    return w3


def get_usdc_contract(w3: Web3):
    """Get USDC contract instance."""
    return w3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS),
        abi=TRANSFER_AUTH_ABI
    )


def settle_payment(request: SettlementRequest) -> str:
    """
    Call USDC.transferWithAuthorization() with the signed authorization.
    Returns transaction hash on success.
    """
    if not FACILITATOR_PRIVATE_KEY:
        raise RuntimeError("FACILITATOR_PRIVATE_KEY not set")
    
    w3 = get_web3()
    usdc = get_usdc_contract(w3)
    
    # Get facilitator account
    account = w3.eth.account.from_key(FACILITATOR_PRIVATE_KEY)
    
    # Parse hex values
    nonce_bytes = bytes.fromhex(request.nonce[2:] if request.nonce.startswith("0x") else request.nonce)
    r_bytes = bytes.fromhex(request.r[2:] if request.r.startswith("0x") else request.r)
    s_bytes = bytes.fromhex(request.s[2:] if request.s.startswith("0x") else request.s)
    
    # Build transaction
    tx = usdc.functions.transferWithAuthorization(
        Web3.to_checksum_address(request.from_address),
        Web3.to_checksum_address(request.to),
        request.value,
        request.valid_after,
        request.valid_before,
        nonce_bytes,
        request.v,
        r_bytes,
        s_bytes
    ).build_transaction({
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 100000,
        "maxFeePerGas": w3.eth.gas_price * 2,
        "maxPriorityFeePerGas": w3.eth.gas_price,
    })
    
    # Sign and send
    signed_tx = w3.eth.account.sign_transaction(tx, FACILITATOR_PRIVATE_KEY)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    
    # Wait for confirmation
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    
    if receipt["status"] != 1:
        raise RuntimeError(f"Transaction failed: {tx_hash.hex()}")
    
    return tx_hash.hex()


# FastAPI app
app = FastAPI(title="EIP-3009 Facilitator")


@app.get("/")
async def root():
    """Health check."""
    w3 = get_web3()
    return {
        "status": "ok",
        "chain_id": w3.eth.chain_id,
        "block": w3.eth.block_number,
        "usdc": USDC_ADDRESS
    }


@app.get("/balance/{address}")
async def get_balance(address: str):
    """Get USDC balance for an address."""
    w3 = get_web3()
    usdc = get_usdc_contract(w3)
    balance = usdc.functions.balanceOf(Web3.to_checksum_address(address)).call()
    return {
        "address": address,
        "balance": balance,
        "balance_usdc": balance / 1_000_000  # USDC has 6 decimals
    }


@app.post("/settle")
async def settle(request: SettlementRequest):
    """
    Settle an EIP-3009 transferWithAuthorization.
    
    This is the core facilitator endpoint - it takes the signed
    authorization and submits it on-chain.
    """
    try:
        tx_hash = settle_payment(request)
        return {
            "status": "success",
            "tx_hash": tx_hash,
            "explorer": f"https://sepolia.basescan.org/tx/{tx_hash}"
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# Test functions
def test_connection():
    """Test Web3 connection."""
    print("Testing Web3 connection...")
    w3 = get_web3()
    print(f"  Connected: {w3.is_connected()}")
    print(f"  Chain ID: {w3.eth.chain_id}")
    print(f"  Block: {w3.eth.block_number}")
    return True


def test_contract():
    """Test USDC contract access."""
    print("\nTesting USDC contract...")
    w3 = get_web3()
    usdc = get_usdc_contract(w3)
    
    # Test balance query
    test_addr = "0x036CbD53842c5426634e7929541eC2318f3dCF7e"  # USDC contract itself
    balance = usdc.functions.balanceOf(test_addr).call()
    print(f"  Contract address: {USDC_ADDRESS}")
    print(f"  Test balance query: {balance}")
    return True


def test_facilitator_wallet():
    """Test facilitator wallet."""
    print("\nTesting facilitator wallet...")
    if not FACILITATOR_PRIVATE_KEY:
        print("  FACILITATOR_PRIVATE_KEY not set - skipping")
        return False
    
    w3 = get_web3()
    account = w3.eth.account.from_key(FACILITATOR_PRIVATE_KEY)
    balance = w3.eth.get_balance(account.address)
    
    print(f"  Address: {account.address}")
    print(f"  ETH Balance: {w3.from_wei(balance, 'ether')} ETH")
    
    if balance == 0:
        print("  WARNING: Facilitator has no ETH for gas!")
        return False
    
    return True


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # Run tests
        print("=" * 50)
        print("EIP-3009 Facilitator Tests")
        print("=" * 50)
        
        try:
            test_connection()
            test_contract()
            test_facilitator_wallet()
            print("\n✓ All tests passed!")
        except Exception as e:
            print(f"\n✗ Test failed: {e}")
            sys.exit(1)
    else:
        # Run server
        import uvicorn
        print("Starting EIP-3009 Facilitator...")
        print(f"USDC: {USDC_ADDRESS}")
        print(f"RPC: {BASE_SEPOLIA_RPC}")
        uvicorn.run(app, host="0.0.0.0", port=4021)

