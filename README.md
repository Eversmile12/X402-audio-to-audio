# x402hz

**Payments over sound. Because why not.**

x402 made payments native to HTTP. I made them native to _air_.

This is a proof-of-concept showing that the payment primitive underneath x402, [EIP-3009](https://eips.ethereum.org/EIPS/eip-3009), doesn't care how bytes travel. HTTP is just one transport. Sound is another. Light could be next.

![x402hz UI](assets/image.png)

---

## The Point

The [x402 protocol](https://docs.cdp.coinbase.com/x402) is brilliant, it embeds payments into HTTP, the backbone of the web. But here's the thing: **the cryptography doesn't know it's traveling over HTTP**.

EIP-3009 (`transferWithAuthorization`) lets you sign a payment authorization offline. Someone else submits it on-chain. The signature travels between you and the merchant however you want:

-   HTTP → That's x402
-   **Sound waves → That's x402hz**
-   QR codes → Scan to pay
-   NFC → Tap to pay
-   Bluetooth → Bump to pay
-   Light pulses → Li-Fi payments
-   Carrier pigeon → Okay maybe not

**138 bytes**. That's all a complete payment handshake needs. Small enough to beep through a speaker.

---

## How It Works

```
┌──────────────┐                              ┌──────────────┐
│    SELLER    │ ──── 🔊 2400Hz tones ─────── │    BUYER     │
│              │                              │              │
│              │ ◄─── 🔊 2400Hz tones ─────── │   (signs)    │
└──────┬───────┘                              └──────────────┘
       │
       ▼
┌──────────────┐
│  Settlement  │ ──── USDC.transferWithAuthorization() ──── Base
└──────────────┘
```

1. Seller broadcasts **"pay me $0.001"** as audio (30 bytes)
2. Buyer's device decodes, signs EIP-3009 authorization locally
3. Buyer broadcasts **signed payment** back as audio (108 bytes)
4. Seller settles on-chain

**Total time:** ~36 seconds of beeping. Worth it for the flex.

---

## The Bigger Picture

This isn't about audio being practical (it's not). It's about proving that **payments can travel any medium**.

| Medium        | How             | Practical?  |
| ------------- | --------------- | ----------- |
| HTTP          | x402            | ✅ Yes      |
| Sound         | x402hz (this)   | 🎭 For fun  |
| QR Code       | Display → Scan  | ✅ Yes      |
| NFC           | Tap             | ✅ Yes      |
| Bluetooth     | Proximity       | ✅ Yes      |
| Light (Li-Fi) | Pulses          | 🔬 Research |


The primitive is transport-agnostic. x402 chose HTTP because it's everywhere. I chose sound because it's ridiculous and proves the point.

---

## Try It Yourself

### Prerequisites

-   Python 3.11+
-   Two devices with speakers/microphones (or one device, two browser tabs)
-   Base Sepolia testnet wallets with USDC ([faucet](https://portal.cdp.coinbase.com/products/faucet))

### Setup

```bash
git clone https://github.com/anthropics/x402hz.git
cd x402hz

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Configure

Create `.env`:

```bash
SELLER_ADDRESS=0xYourSellerAddress
BUYER_ADDRESS=0xYourBuyerAddress
BUYER_PRIVATE_KEY=0xYourBuyerPrivateKey
FACILITATOR_PRIVATE_KEY=0xFacilitatorWalletForGas
```

### Run

```bash
# Terminal 1
python ui_seller.py    # http://localhost:5001

# Terminal 2
python ui_buyer.py     # http://localhost:5002
```

1. Open both UIs
2. Buyer clicks **"Activate Listener"**
3. Seller clicks **"Initiate Request"**
5. Watch USDC move on-chain

---

## Technical Details

### Payload Compression

Standard x402 JSON is ~1KB. Too fat for audio. x402hz compresses it to:

| Payload  | JSON       | Compact       |
| -------- | ---------- | ------------- |
| Request  | ~800 bytes | **30 bytes**  |
| Response | ~600 bytes | **108 bytes** |

### Audio Modem

-   **Frequency:** 2400 Hz (chosen to cut through crowd noise)
-   **Modulation:** OOK (On-Off Keying)
-   **Bit rate:** 100 baud
-   **Error correction:** 3x repetition + CRC-16
-   **Detection:** Goertzel algorithm (laser-focused on 2400 Hz)

Survives background noise, conversations, and questionable life choices.

### Project Structure

```
├── ui_seller.py        # Seller web UI
├── ui_buyer.py         # Buyer web UI
├── payment.py          # Signing + encoding
├── facilitator.py      # On-chain settlement
├── config.py           # Shared config
└── fsk_modem.py        # Audio modem
```

---

## What This Proves

1. **EIP-3009 is the primitive.** x402 is one application of it. There can be many.

2. **Authorization ≠ Transport.** Sign offline, transmit however, settle on-chain.

3. **Payments can be weird.** And that's okay.

---

## What This Doesn't Prove

-   That audio payments are practical (they're not)
-   That you should use this in production (please don't)
-   That I have good judgment (debatable)

---

## Acknowledgments

Huge thanks to the [Coinbase x402 team](https://docs.cdp.coinbase.com/x402) for building the protocol that made this possible. x402 is genuinely important infrastructure for web payments. I just... took it off-road.

Also thanks to EIP-3009 for existing since 2020 and being criminally underused until now.

---

## License

MIT - Do weird things with payments.

---

_Built to answer: "If payments can travel over HTTP, what else can they travel over?"_

_Answer: Literally anything that can carry 138 bytes._
