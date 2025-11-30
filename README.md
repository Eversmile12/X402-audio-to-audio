# x402 Audio-to-audio Demo

**USDC payments transmitted over sound waves.**

This project demonstrates Coinbase's [x402 protocol](https://docs.cdp.coinbase.com/x402) working over audio instead of HTTP. A seller broadcasts a payment request as sound, the buyer's device listens, signs the payment, and transmits the authorization back, all through audible tones.

![X402 Audio Protocol UI](assets/image.png)

---

## How It Works

```
┌──────────────┐                              ┌──────────────┐
│  SELLER UI   │ ──── audio (2400Hz OOK) ──── │  BUYER UI    │
│  (client 1)  │                              │  (client 2)  │
│              │ ◄─── audio (2400Hz OOK) ──── │              │
└──────┬───────┘                              └──────────────┘
       │
       ▼
┌──────────────┐
│ x402 Server  │ ──── HTTP ──── x402 Facilitator ──── Base Sepolia
└──────────────┘
```

1. **Seller** broadcasts a compact payment request (~54 bytes) as audio
2. **Buyer** decodes, signs an EIP-712 payment authorization
3. **Buyer** transmits the signed response (~116 bytes) back as audio
4. **Seller** decodes and verifies via x402 Facilitator

---

## Prerequisites

-   **Python 3.11+**
-   **One or two devices with speakers/microphones**
-   **Base Sepolia testnet wallets** with:
    -   USDC (get from [Coinbase faucet](https://portal.cdp.coinbase.com/products/faucet))

---

## Quickstart

### 1. Clone and Setup

```bash
git clone https://github.com/your-repo/x402-demo.git
cd x402-demo

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment

Create a `.env` file with exactly these 3 variables:

```bash
# Seller's wallet address (receives payment)
SELLER_ADDRESS=0xYourSellerAddress

# Buyer's wallet address
BUYER_ADDRESS=0xYourBuyerAddress

# Buyer's private key (signs payment authorization)
BUYER_PRIVATE_KEY=0xYourBuyerPrivateKey
```

⚠️ **Never commit real private keys.** Use testnet wallets only.

### 3. Run the Demo

Open **three terminal windows**:

```bash
# Terminal 1: x402 verification server
source venv/bin/activate
python server_x402.py
```

```bash
# Terminal 2: Seller UI (http://localhost:5001)
source venv/bin/activate
python ui_seller.py
```

```bash
# Terminal 3: Buyer UI (http://localhost:5002)
source venv/bin/activate
python ui_buyer.py
```

### 4. Execute Payment

1. Open **Seller UI** at `http://localhost:5001`
2. Open **Buyer UI** at `http://localhost:5002`
3. On Buyer: Click **"Activate Listener"**
4. On Seller: Click **"Initiate Request"**
5. Wait for audio exchange (~15-20 seconds total)
6. Watch USDC balances update!

---

## Project Structure

```
x402-demo/
├── server_x402.py      # x402 payment verification server (FastAPI)
├── ui_seller.py        # Seller web UI (Flask)
├── ui_buyer.py         # Buyer web UI (Flask)
├── fsk_modem.py        # Audio modem (OOK modulation + Goertzel detection)
├── compact_x402.py     # Compact binary encoding for x402 payloads
├── requirements.txt    # Python dependencies
├── BLOG.md             # Technical write-up
└── *.wav               # Debug audio files (auto-generated)
```

---

## Environment Variables

| Variable            | Description                        | Used By                          |
| ------------------- | ---------------------------------- | -------------------------------- |
| `SELLER_ADDRESS`    | Wallet address to receive payments | `server_x402.py`, `ui_seller.py` |
| `BUYER_ADDRESS`     | Buyer's wallet address             | `ui_seller.py`                   |
| `BUYER_PRIVATE_KEY` | Buyer's private key for signing    | `ui_buyer.py`                    |

---

## Compact x402 Encoding

Standard x402 uses JSON payloads (~1KB+) — way too large for audio transmission. I created a **compact binary encoding** that preserves all cryptographic data:

| Payload          | Standard x402   | Compact Binary |
| ---------------- | --------------- | -------------- |
| Payment Request  | ~800 bytes JSON | **54 bytes**   |
| Payment Response | ~600 bytes JSON | **116 bytes**  |

This 10-15x reduction makes audio transmission practical (~15-20 seconds total vs several minutes).

See `compact_x402.py` for the encoding/decoding implementation.

---

## Audio Modem Details

-   **Modulation**: OOK (On-Off Keying) at 2400 Hz
-   **Bit rate**: 100 baud (10ms per bit)
-   **Redundancy**: 2x repetition coding with majority voting
-   **Error detection**: CRC-16
-   **Noise rejection**:
    -   Goertzel algorithm for precise 2400Hz tone detection
    -   4th-order Butterworth bandpass filter (2000-2800 Hz)

---

## Testing Without Two Devices

You can test the modem with generated WAV files:

```python
from fsk_modem import encode_fsk, decode_fsk
import numpy as np

# Encode test data
data = b"Hello x402!"
audio = encode_fsk(data)

# Add some noise (optional)
noisy = audio + np.random.normal(0, 0.1, len(audio)).astype(np.float32)

# Decode
result = decode_fsk(noisy)
print(f"Decoded: {result}")  # b'Hello x402!'
```

---

## Troubleshooting

### "Failed to decode" errors

-   **Check volume**: Speaker output should be clearly audible
-   **Check timing**: Start buyer listener before seller broadcasts
-   **Check microphone**: Ensure correct input device is selected
-   **Reduce noise**: Move to quieter environment

### Port already in use

```bash
# Kill process on port 5001
lsof -ti:5001 | xargs kill -9

# Kill process on port 4021
lsof -ti:4021 | xargs kill -9
```

### No USDC balance

Get testnet USDC from the [Coinbase Developer Faucet](https://portal.cdp.coinbase.com/products/faucet).

---

## Future Improvements

-   **Offline-first**: Queue payments for later settlement
-   **Direct settlement**: Skip Facilitator, call USDC contract directly
-   **Stronger FEC**: Reed-Solomon codes for error correction
-   **FSK modulation**: Better performance in reverberant spaces
-   **Mobile apps**: iOS/Android native implementations

---

## License

MIT

---

## Acknowledgments

-   [Coinbase x402 Protocol](https://docs.cdp.coinbase.com/x402)
-   Built during a weekend hack session to answer: "What if payments could travel through air?"
