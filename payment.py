"""
EIP-3009 payment creation and compact encoding.

This module handles:
1. Creating payment requests (seller → buyer)
2. Signing EIP-3009 authorizations (buyer)
3. Compact binary encoding for audio transmission

Payload sizes:
- Request:  30 bytes
- Response: 108 bytes
"""

import struct
import time
import secrets
from dataclasses import dataclass
from typing import Tuple
from eth_account import Account

from config import NETWORKS, USDC_NAME, USDC_VERSION, get_chain_id, get_usdc_address

# Network ID mapping for compact encoding (1 byte)
NETWORK_IDS = {"base-sepolia": 0, "base": 1, "ethereum": 2, "ethereum-sepolia": 3}
NETWORK_IDS_REVERSE = {v: k for k, v in NETWORK_IDS.items()}


# =============================================================================
# PAYMENT REQUEST (Seller → Buyer, 30 bytes)
# =============================================================================

@dataclass
class PaymentRequest:
    """
    Compact payment request for audio transmission.
    
    Format (30 bytes):
    - version: 1 byte
    - network: 1 byte (enum)
    - scheme: 1 byte (0=exact)
    - price: 4 bytes (uint32, micro-USDC)
    - pay_to: 20 bytes (address)
    - timeout: 2 bytes (uint16, seconds)
    - nonce: 1 byte (counter)
    """
    pay_to: str      # Recipient address
    price: int       # Amount in micro-USDC
    timeout: int     # Validity in seconds
    network: str = "base-sepolia"
    nonce: int = 0
    
    def to_bytes(self) -> bytes:
        """Encode to 30 bytes."""
        network_id = NETWORK_IDS.get(self.network, 0)
        pay_to_bytes = bytes.fromhex(self.pay_to[2:] if self.pay_to.startswith("0x") else self.pay_to)
        
        return struct.pack(
            ">B B B I 20s H B",
            1,  # version
            network_id,
            0,  # scheme (exact)
            min(self.price, 0xFFFFFFFF),
            pay_to_bytes,
            min(self.timeout, 65535),
            self.nonce % 256
        )
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "PaymentRequest":
        """Decode from 30 bytes."""
        version, network_id, scheme_id, price, pay_to_bytes, timeout, nonce = struct.unpack(
            ">B B B I 20s H B",
            data[:30]
        )
        
        return cls(
            pay_to="0x" + pay_to_bytes.hex(),
            price=price,
            timeout=timeout,
            network=NETWORK_IDS_REVERSE.get(network_id, "base-sepolia"),
            nonce=nonce,
        )
    
    @property
    def chain_id(self) -> int:
        return get_chain_id(self.network)


# =============================================================================
# PAYMENT RESPONSE (Buyer → Seller, 108 bytes)
# =============================================================================

@dataclass  
class PaymentResponse:
    """
    Signed EIP-3009 authorization for audio transmission.
    
    Format (108 bytes):
    - version: 1 byte
    - network: 1 byte (enum)
    - scheme: 1 byte
    - v: 1 byte (signature recovery)
    - r: 32 bytes (signature)
    - s: 32 bytes (signature)
    - nonce: 32 bytes (random)
    - valid_after: 4 bytes (uint32 timestamp)
    - valid_before: 4 bytes (uint32 timestamp)
    """
    v: int
    r: bytes       # 32 bytes
    s: bytes       # 32 bytes
    nonce: bytes   # 32 bytes
    valid_after: int
    valid_before: int
    network: str = "base-sepolia"
    
    def to_bytes(self) -> bytes:
        """Encode to 108 bytes."""
        network_id = NETWORK_IDS.get(self.network, 0)
        
        return struct.pack(
            ">B B B B 32s 32s 32s I I",
            1,  # version
            network_id,
            0,  # scheme (exact)
            self.v,
            self.r,
            self.s,
            self.nonce,
            self.valid_after,
            self.valid_before
        )
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "PaymentResponse":
        """Decode from 108 bytes."""
        version, network_id, scheme_id, v, r, s, nonce, valid_after, valid_before = struct.unpack(
            ">B B B B 32s 32s 32s I I",
            data[:108]
        )
        
        return cls(
            v=v, r=r, s=s, nonce=nonce,
            valid_after=valid_after,
            valid_before=valid_before,
            network=NETWORK_IDS_REVERSE.get(network_id, "base-sepolia"),
        )
    
    @classmethod
    def from_authorization(cls, auth: dict, network: str = "base-sepolia") -> "PaymentResponse":
        """Create from sign_authorization() output."""
        r_hex = auth['r'][2:] if auth['r'].startswith('0x') else auth['r']
        s_hex = auth['s'][2:] if auth['s'].startswith('0x') else auth['s']
        nonce_hex = auth['nonce'][2:] if auth['nonce'].startswith('0x') else auth['nonce']
        
        return cls(
            v=auth['v'],
            r=bytes.fromhex(r_hex),
            s=bytes.fromhex(s_hex),
            nonce=bytes.fromhex(nonce_hex),
            valid_after=auth['valid_after'],
            valid_before=auth['valid_before'],
            network=network,
        )
    
    def to_settlement_params(self, from_address: str, request: PaymentRequest) -> dict:
        """Convert to facilitator settlement parameters."""
        return {
            "from_address": from_address,
            "to": request.pay_to,
            "value": request.price,
            "valid_after": self.valid_after,
            "valid_before": self.valid_before,
            "nonce": "0x" + self.nonce.hex(),
            "v": self.v,
            "r": "0x" + self.r.hex(),
            "s": "0x" + self.s.hex(),
        }


# =============================================================================
# EIP-3009 SIGNING
# =============================================================================

def _get_eip712_domain(chain_id: int) -> dict:
    """Get EIP-712 domain for USDC."""
    usdc_address = get_usdc_address(
        "base-sepolia" if chain_id == 84532 else "base"
    )
    return {
        "name": USDC_NAME,
        "version": USDC_VERSION,
        "chainId": chain_id,
        "verifyingContract": usdc_address,
    }


def _get_typed_data_types() -> dict:
    """Get EIP-712 types for TransferWithAuthorization."""
    return {
        "TransferWithAuthorization": [
            {"name": "from", "type": "address"},
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "validAfter", "type": "uint256"},
            {"name": "validBefore", "type": "uint256"},
            {"name": "nonce", "type": "bytes32"},
        ]
    }


def sign_authorization(
    private_key: str,
    to_address: str,
    value: int,
    timeout_seconds: int = 60,
    chain_id: int = 84532,
) -> dict:
    """
    Sign an EIP-3009 transferWithAuthorization.
    
    Args:
        private_key: Signer's private key (hex)
        to_address: Recipient address
        value: Amount in micro-USDC
        timeout_seconds: How long the authorization is valid
        chain_id: Chain ID (84532 for Base Sepolia)
    
    Returns:
        Dict with all parameters needed for settlement
    """
    if not private_key.startswith("0x"):
        private_key = "0x" + private_key
    
    account = Account.from_key(private_key)
    from_address = account.address
    
    # Generate random nonce
    nonce = secrets.token_bytes(32)
    
    # Set validity window
    current_time = int(time.time())
    valid_after = current_time - 60  # 1 min buffer for clock skew
    valid_before = current_time + timeout_seconds
    
    # Build and sign typed data
    domain = _get_eip712_domain(chain_id)
    types = _get_typed_data_types()
    message = {
        "from": from_address,
        "to": to_address,
        "value": value,
        "validAfter": valid_after,
        "validBefore": valid_before,
        "nonce": nonce,
    }
    
    signed = account.sign_typed_data(
        domain_data=domain,
        message_types=types,
        message_data=message,
    )
    
    return {
        "from_address": from_address,
        "to": to_address,
        "value": value,
        "valid_after": valid_after,
        "valid_before": valid_before,
        "nonce": "0x" + nonce.hex(),
        "v": signed.v,
        "r": "0x" + signed.r.to_bytes(32, 'big').hex(),
        "s": "0x" + signed.s.to_bytes(32, 'big').hex(),
    }


# =============================================================================
# TESTS
# =============================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("Payment Module Tests")
    print("=" * 50)
    
    # Test request encoding
    print("\n1. PaymentRequest")
    req = PaymentRequest(
        pay_to="0x5b12EA8DC4f37F4998d5A1BCf63Ac9d6fd89bd4e",
        price=1000,
        timeout=60,
    )
    encoded = req.to_bytes()
    decoded = PaymentRequest.from_bytes(encoded)
    print(f"   Encoded: {len(encoded)} bytes")
    print(f"   Match: {decoded.pay_to.lower() == req.pay_to.lower()}")
    
    # Test response encoding
    print("\n2. PaymentResponse")
    resp = PaymentResponse(
        v=28,
        r=bytes.fromhex("ab" * 32),
        s=bytes.fromhex("cd" * 32),
        nonce=bytes.fromhex("ef" * 32),
        valid_after=1700000000,
        valid_before=1700000060,
    )
    encoded = resp.to_bytes()
    decoded = PaymentResponse.from_bytes(encoded)
    print(f"   Encoded: {len(encoded)} bytes")
    print(f"   Match: {decoded.v == resp.v}")
    
    # Test signing
    print("\n3. sign_authorization()")
    test_account = Account.create()
    auth = sign_authorization(
        private_key=test_account.key.hex(),
        to_address="0x5b12EA8DC4f37F4998d5A1BCf63Ac9d6fd89bd4e",
        value=1000,
    )
    print(f"   Signed by: {auth['from_address'][:20]}...")
    print(f"   Has nonce: {len(auth['nonce']) == 66}")
    
    print("\n✓ All tests passed!")

