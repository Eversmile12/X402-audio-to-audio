"""
Shared configuration for EIP-3009 audio payments.
"""

import os
from dotenv import load_dotenv
from web3 import Web3

load_dotenv()

# RPC endpoint
BASE_SEPOLIA_RPC = os.getenv(
    "BASE_SEPOLIA_RPC",
    "https://base-sepolia.g.alchemy.com/v2/HKxtPZtjcol46DdnHnuCHTCGQyLIET_N"
)

# Network configuration
NETWORKS = {
    "base-sepolia": {"chain_id": 84532, "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"},
    "base": {"chain_id": 8453, "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"},
}

# Default network
DEFAULT_NETWORK = "base-sepolia"

# USDC EIP-712 domain
USDC_NAME = "USDC"
USDC_VERSION = "2"

# Minimal USDC ABI (balanceOf only)
USDC_ABI = [
    {
        "inputs": [{"name": "account", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function"
    }
]


def get_web3() -> Web3:
    """Get Web3 connection."""
    return Web3(Web3.HTTPProvider(BASE_SEPOLIA_RPC))


def get_usdc_balance(address: str, network: str = DEFAULT_NETWORK) -> float:
    """Get USDC balance for an address (returns float in USDC, not micro)."""
    try:
        w3 = get_web3()
        usdc_address = NETWORKS[network]["usdc"]
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(usdc_address),
            abi=USDC_ABI
        )
        balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return balance / 1_000_000  # USDC has 6 decimals
    except Exception as e:
        print(f"[DEBUG] Balance error: {e}")
        return 0.0


def get_chain_id(network: str = DEFAULT_NETWORK) -> int:
    """Get chain ID for network."""
    return NETWORKS.get(network, NETWORKS[DEFAULT_NETWORK])["chain_id"]


def get_usdc_address(network: str = DEFAULT_NETWORK) -> str:
    """Get USDC contract address for network."""
    return NETWORKS.get(network, NETWORKS[DEFAULT_NETWORK])["usdc"]

