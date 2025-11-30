"""
Compact binary encoding for x402 payment data.

Reduces ~1200 bytes of JSON to ~138 bytes of binary while preserving
all data needed for cryptographic verification.

Request: 30 bytes (implicit USDC asset, 4-byte price)
Response: 108 bytes (4-byte timestamps)
"""

import struct
import json
import base64
from dataclasses import dataclass
from typing import Optional
from eth_account import Account


# Network ID mapping (1 byte instead of string)
NETWORKS = {
    "base-sepolia": 0,
    "base": 1,
    "ethereum": 2,
    "ethereum-sepolia": 3,
}
NETWORKS_REVERSE = {v: k for k, v in NETWORKS.items()}

# Well-known asset addresses (can skip transmitting if using USDC)
USDC_ADDRESSES = {
    "base-sepolia": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
    "base": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
}


@dataclass
class CompactPaymentRequest:
    """
    Compact binary encoding of x402 payment requirements.
    
    Format (30 bytes total):
    - version: 1 byte (uint8)
    - network: 1 byte (uint8, enum)
    - scheme: 1 byte (uint8, 0=exact)
    - price: 4 bytes (uint32, micro-units, max ~$4000)
    - pay_to: 20 bytes (address)
    - timeout: 2 bytes (uint16, seconds)
    - nonce: 1 byte (uint8, simple counter)
    
    Asset address is implicit (USDC based on network).
    """
    version: int
    network: str
    scheme: str
    price: int  # in base units (e.g., micro-USDC)
    pay_to: str  # 0x address
    asset: str   # 0x address (derived from network, not transmitted)
    timeout: int  # seconds
    nonce: int
    
    # Optional fields not transmitted but needed for reconstruction
    resource: str = ""
    description: str = ""
    
    def to_bytes(self) -> bytes:
        """Encode to compact binary format (30 bytes)."""
        network_id = NETWORKS.get(self.network, 0)
        scheme_id = 0 if self.scheme == "exact" else 1
        
        pay_to_bytes = bytes.fromhex(self.pay_to[2:])
        
        # Asset is implicit (USDC) - not transmitted
        return struct.pack(
            ">B B B I 20s H B",
            self.version,
            network_id,
            scheme_id,
            min(self.price, 0xFFFFFFFF),  # 4-byte max
            pay_to_bytes,
            min(self.timeout, 65535),
            self.nonce % 256
        )
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "CompactPaymentRequest":
        """Decode from compact binary format (30 bytes)."""
        version, network_id, scheme_id, price, pay_to_bytes, timeout, nonce = struct.unpack(
            ">B B B I 20s H B",
            data[:30]
        )
        
        network = NETWORKS_REVERSE.get(network_id, "base-sepolia")
        # Derive asset from network (implicit USDC)
        asset = USDC_ADDRESSES.get(network, USDC_ADDRESSES["base-sepolia"])
        
        return cls(
            version=version,
            network=network,
            scheme="exact" if scheme_id == 0 else "unknown",
            price=price,
            pay_to="0x" + pay_to_bytes.hex(),
            asset=asset,
            timeout=timeout,
            nonce=nonce
        )
    
    @classmethod
    def from_402_response(cls, response_json: dict, nonce: int = 0) -> "CompactPaymentRequest":
        """Create from standard x402 402 response body."""
        accept = response_json["accepts"][0]  # Use first accept option
        
        return cls(
            version=response_json.get("x402Version", 1),
            network=accept["network"],
            scheme=accept["scheme"],
            price=int(accept["maxAmountRequired"]),
            pay_to=accept["payTo"],
            asset=accept["asset"],
            timeout=accept.get("maxTimeoutSeconds", 60),
            nonce=nonce,
            resource=accept.get("resource", ""),
            description=accept.get("description", "")
        )
    
    def to_402_response(self) -> dict:
        """Reconstruct full x402 402 response JSON."""
        return {
            "x402Version": self.version,
            "accepts": [{
                "scheme": self.scheme,
                "network": self.network,
                "maxAmountRequired": str(self.price),
                "resource": self.resource,
                "description": self.description,
                "mimeType": "",
                "payTo": self.pay_to,
                "maxTimeoutSeconds": self.timeout,
                "asset": self.asset,
                "extra": {"name": "USDC", "version": "2"}
            }]
        }


@dataclass  
class CompactPaymentResponse:
    """
    Compact binary encoding of x402 payment header.
    
    Format (108 bytes total):
    - version: 1 byte (uint8)
    - network: 1 byte (uint8, enum)
    - scheme: 1 byte (uint8)
    - signature_v: 1 byte (uint8)
    - signature_r: 32 bytes
    - signature_s: 32 bytes
    - nonce: 32 bytes (hex string in original)
    - valid_after: 4 bytes (uint32, unix timestamp - works until 2106)
    - valid_before: 4 bytes (uint32, unix timestamp)
    """
    version: int
    network: str
    scheme: str
    signature: str  # Full 0x... signature (65 bytes)
    nonce: str  # 32-byte hex nonce (0x...)
    valid_after: int  # Unix timestamp
    valid_before: int  # Unix timestamp
    
    def to_bytes(self) -> bytes:
        """Encode to compact binary format (108 bytes)."""
        network_id = NETWORKS.get(self.network, 0)
        scheme_id = 0 if self.scheme == "exact" else 1
        
        # Parse signature (remove 0x, split into r, s, v)
        sig_hex = self.signature[2:] if self.signature.startswith("0x") else self.signature
        sig_bytes = bytes.fromhex(sig_hex)
        
        # Signature is 65 bytes: r(32) + s(32) + v(1)
        r = sig_bytes[:32]
        s = sig_bytes[32:64]
        v = sig_bytes[64] if len(sig_bytes) > 64 else 27
        
        # Parse nonce (32 bytes)
        nonce_hex = self.nonce[2:] if self.nonce.startswith("0x") else self.nonce
        nonce_bytes = bytes.fromhex(nonce_hex)
        
        return struct.pack(
            ">B B B B 32s 32s 32s I I",
            self.version,
            network_id,
            scheme_id,
            v,
            r,
            s,
            nonce_bytes,
            self.valid_after,
            self.valid_before
        )
    
    @classmethod
    def from_bytes(cls, data: bytes) -> "CompactPaymentResponse":
        """Decode from compact binary format (108 bytes)."""
        version, network_id, scheme_id, v, r, s, nonce_bytes, valid_after, valid_before = struct.unpack(
            ">B B B B 32s 32s 32s I I",
            data[:108]
        )
        
        # Reconstruct signature
        signature = "0x" + r.hex() + s.hex() + format(v, '02x')
        nonce = "0x" + nonce_bytes.hex()
        
        return cls(
            version=version,
            network=NETWORKS_REVERSE.get(network_id, "base-sepolia"),
            scheme="exact" if scheme_id == 0 else "unknown",
            signature=signature,
            nonce=nonce,
            valid_after=valid_after,
            valid_before=valid_before
        )
    
    @classmethod
    def from_x_payment_header(cls, header_base64: str) -> "CompactPaymentResponse":
        """Create from standard x-payment header."""
        header_json = json.loads(base64.b64decode(header_base64))
        payload = header_json.get("payload", {})
        authorization = payload.get("authorization", {})
        
        return cls(
            version=header_json.get("x402Version", 1),
            network=header_json.get("network", "base-sepolia"),
            scheme=header_json.get("scheme", "exact"),
            signature=payload.get("signature", ""),
            nonce=authorization.get("nonce", "0x" + "00" * 32),
            valid_after=int(authorization.get("validAfter", 0)),
            valid_before=int(authorization.get("validBefore", 0))
        )
    
    def to_x_payment_header(self, payment_request: CompactPaymentRequest, from_address: str) -> str:
        """
        Reconstruct full x-payment header JSON.
        Needs the original payment request and sender address.
        """
        header = {
            "x402Version": self.version,
            "scheme": self.scheme,
            "network": self.network,
            "payload": {
                "signature": self.signature,
                "authorization": {
                    "from": from_address,
                    "to": payment_request.pay_to,
                    "value": str(payment_request.price),
                    "validAfter": str(self.valid_after),
                    "validBefore": str(self.valid_before),
                    "nonce": self.nonce,
                }
            }
        }
        
        return base64.b64encode(json.dumps(header).encode()).decode()


def test_compact_encoding():
    """Test the compact encoding/decoding."""
    print("=" * 50)
    print("Testing Compact x402 Encoding")
    print("=" * 50)
    
    # Test payment request
    print("\n1. Payment Request Encoding")
    request = CompactPaymentRequest(
        version=1,
        network="base-sepolia",
        scheme="exact",
        price=1000,  # $0.001 in micro-USDC
        pay_to="0x5b12EA8DC4f37F4998d5A1BCf63Ac9d6fd89bd4e",
        asset="0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Will be derived, not transmitted
        timeout=60,
        nonce=1
    )
    
    encoded = request.to_bytes()
    print(f"   Original: network={request.network}, price={request.price}")
    print(f"   Encoded: {len(encoded)} bytes (was 54)")
    
    decoded = CompactPaymentRequest.from_bytes(encoded)
    print(f"   Decoded: network={decoded.network}, price={decoded.price}, asset={decoded.asset[:10]}...")
    print(f"   Match: {decoded.network == request.network and decoded.price == request.price}")
    
    # Test payment response
    print("\n2. Payment Response Encoding")
    response = CompactPaymentResponse(
        version=1,
        network="base-sepolia",
        scheme="exact",
        signature="0x" + "ab" * 32 + "cd" * 32 + "1b",  # Fake signature
        nonce="0x" + "ef" * 32,  # 32-byte nonce
        valid_after=1700000000,
        valid_before=1700000060
    )
    
    encoded = response.to_bytes()
    print(f"   Original: valid_before={response.valid_before}")
    print(f"   Encoded: {len(encoded)} bytes (was 116)")
    
    decoded = CompactPaymentResponse.from_bytes(encoded)
    print(f"   Decoded: valid_before={decoded.valid_before}")
    print(f"   Match: {decoded.valid_before == response.valid_before and decoded.nonce == response.nonce}")
    
    # Total size
    print("\n3. Size Summary")
    req_size = 30
    resp_size = 108
    print(f"   Payment request: {req_size} bytes (was 54)")
    print(f"   Payment response: {resp_size} bytes (was 116)")
    print(f"   Total: {req_size + resp_size} bytes (was 170)")
    print(f"   Savings: {170 - (req_size + resp_size)} bytes ({(170 - (req_size + resp_size)) * 100 // 170}%)")
    print(f"   vs JSON: ~1200 bytes → {100 - (req_size + resp_size) * 100 // 1200}% compression")


if __name__ == "__main__":
    test_compact_encoding()

