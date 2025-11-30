#!/usr/bin/env python3
"""
x402 Audio Buyer - Web UI
Run this on the BUYER laptop.
"""

import os
import time
import threading
from flask import Flask, render_template_string, jsonify
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
from eth_account import Account
from web3 import Web3
from dotenv import load_dotenv

from fsk_modem import encode_fsk, decode_fsk, SAMPLE_RATE, get_duration
from compact_x402 import CompactPaymentRequest, CompactPaymentResponse

load_dotenv()

# Base Sepolia RPC
w3 = Web3(Web3.HTTPProvider('https://sepolia.base.org'))
USDC_ADDRESS = '0x036CbD53842c5426634e7929541eC2318f3dCF7e'
USDC_ABI = [{"inputs":[{"name":"account","type":"address"}],"name":"balanceOf","outputs":[{"name":"","type":"uint256"}],"stateMutability":"view","type":"function"}]

def get_usdc_balance(address):
    """Get USDC balance for an address."""
    try:
        contract = w3.eth.contract(address=Web3.to_checksum_address(USDC_ADDRESS), abi=USDC_ABI)
        balance = contract.functions.balanceOf(Web3.to_checksum_address(address)).call()
        return balance / 1_000_000  # USDC has 6 decimals
    except Exception as e:
        print(f"[DEBUG] Balance error: {e}")
        return 0.0

app = Flask(__name__)

# Global state
state = {
    "status": "idle",
    "message": "Ready to listen",
    "step": 0,
    "request_decoded": False,
    "payment_sent": False,
    "price": None,
    "seller": None,
    "amplitude": 0.0  # Add amplitude
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>x402 Buyer</title>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link href="https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap" rel="stylesheet">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Share Tech Mono', monospace;
            background-color: #050505;
            background-image: 
                linear-gradient(rgba(18, 16, 16, 0) 50%, rgba(0, 0, 0, 0.25) 50%),
                linear-gradient(90deg, rgba(255, 0, 0, 0.06), rgba(0, 255, 0, 0.02), rgba(0, 0, 255, 0.06));
            background-size: 100% 2px, 6px 100%;
            min-height: 100vh;
            color: #0ff;
            padding: 40px 20px;
            text-shadow: 0 0 5px rgba(0, 255, 255, 0.5);
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            border: 1px solid #0ff;
            padding: 20px;
            box-shadow: 0 0 20px rgba(0, 255, 255, 0.2);
            position: relative;
        }
        .container::before {
            content: "SYSTEM_READY";
            position: absolute;
            top: -10px;
            left: 20px;
            background: #050505;
            padding: 0 10px;
            font-size: 12px;
            color: #0ff;
        }
        .header {
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 1px dashed #0ff;
            padding-bottom: 20px;
        }
        .title {
            font-size: 48px;
            font-weight: 700;
            color: #0ff;
            letter-spacing: 2px;
            text-transform: uppercase;
            animation: glitch 5s infinite;
            position: relative;
        }
        @keyframes glitch {
            0%, 90% { transform: translate(0); text-shadow: none; }
            91% { transform: translate(2px,0) skew(0deg); text-shadow: -2px 0 #ff0000; }
            92% { transform: translate(-2px,0) skew(0deg); text-shadow: 2px 0 #00ff00; }
            93% { transform: translate(0,0) skew(5deg); text-shadow: none; }
            94% { transform: translate(0,0) skew(0deg); }
            100% { transform: translate(0); }
        }
        .subtitle {
            color: #0af;
            margin-top: 8px;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 4px;
        }
        .role-badge {
            display: inline-block;
            border: 1px solid #0ff;
            color: #0ff;
            padding: 4px 12px;
            font-size: 14px;
            font-weight: 600;
            margin-top: 16px;
            text-transform: uppercase;
            background: rgba(0, 255, 255, 0.1);
        }
        .card {
            border: 1px solid #0ff;
            background: rgba(0, 20, 20, 0.3);
            padding: 20px;
            margin-bottom: 20px;
            position: relative;
        }
        .card::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            border: 1px solid rgba(0, 255, 255, 0.1);
            pointer-events: none;
        }
        .status-card {
            display: flex;
            align-items: center;
            gap: 16px;
            border-color: #0f0;
            color: #0f0;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            background: #0f0;
            box-shadow: 0 0 10px #0f0;
        }
        .status-dot.idle { background: #555; box-shadow: none; }
        .status-dot.listening { background: #ff0; box-shadow: 0 0 10px #ff0; animation: blink 0.5s infinite; }
        .status-dot.signing { background: #f0f; box-shadow: 0 0 10px #f0f; }
        .status-dot.playing { background: #0f0; box-shadow: 0 0 10px #0f0; animation: blink 0.1s infinite; }
        .status-dot.success { background: #0ff; box-shadow: 0 0 20px #0ff; }
        .status-dot.error { background: #f00; box-shadow: 0 0 20px #f00; }
        @keyframes blink { 0% { opacity: 1; } 50% { opacity: 0.3; } 100% { opacity: 1; } }
        
        .status-text {
            font-size: 18px;
            text-transform: uppercase;
        }
        .info-grid {
            display: grid;
            gap: 8px;
            font-size: 14px;
        }
        .info-row {
            display: flex;
            justify-content: space-between;
            border-bottom: 1px dotted #333;
            padding: 4px 0;
        }
        .info-label { color: #888; text-transform: uppercase; }
        .info-value { color: #0ff; }
        
        .btn {
            width: 100%;
            padding: 20px;
            background: #000;
            border: 2px solid #0ff;
            color: #0ff;
            font-family: 'Share Tech Mono', monospace;
            font-size: 20px;
            text-transform: uppercase;
            cursor: pointer;
            transition: all 0.1s;
            margin-top: 10px;
            position: relative;
            overflow: hidden;
        }
        .btn:hover {
            background: #0ff;
            color: #000;
            box-shadow: 0 0 20px #0ff;
        }
        .btn:disabled {
            border-color: #555;
            color: #555;
            cursor: not-allowed;
            background: #000;
            box-shadow: none;
        }
        
        .steps {
            display: flex;
            justify-content: space-between;
            margin-bottom: 30px;
            border-bottom: 1px solid #333;
            padding-bottom: 10px;
        }
        .step {
            color: #555;
            font-size: 12px;
            text-transform: uppercase;
        }
        .step.active { color: #0f0; text-shadow: 0 0 5px #0f0; }
        .step.done { color: #0ff; }
        
        .visualizer {
            width: 100%;
            height: 60px;
            background: #000;
            border: 1px solid #333;
            margin-top: 10px;
            position: relative;
            overflow: hidden;
        }
        canvas {
            width: 100%;
            height: 100%;
        }
        
        .balance-amount {
            font-size: 32px;
            color: #0ff;
            text-align: center;
            text-shadow: 0 0 10px rgba(0, 255, 255, 0.5);
        }
        
        .payment-box {
            border: 1px solid #f0f;
            background: rgba(255, 0, 255, 0.1);
            padding: 20px;
            text-align: center;
            margin-bottom: 20px;
            display: none;
        }
        .payment-amount {
            font-size: 36px;
            color: #f0f;
            font-weight: 700;
            text-shadow: 0 0 10px #f0f;
        }
        .payment-label {
            color: #f0f;
            font-size: 12px;
            text-transform: uppercase;
        }
        
        .success-box {
            border: 2px solid #0ff;
            padding: 20px;
            text-align: center;
            margin-top: 20px;
            background: rgba(0, 255, 255, 0.1);
            display: none;
        }
        .success-title {
            font-size: 24px;
            color: #0ff;
            text-transform: uppercase;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">x402</div>
            <div class="subtitle">Audio Protocol v1.0</div>
            <div class="role-badge">BUYER_NODE</div>
        </div>

        <div class="steps">
            <div class="step" id="step1">[01] LISTEN</div>
            <div class="step" id="step2">[02] SIGN</div>
            <div class="step" id="step3">[03] RESPOND</div>
        </div>

        <div class="card status-card">
            <div class="status-dot" id="statusDot"></div>
            <div class="status-text" id="statusText">SYSTEM IDLE</div>
        </div>
        
        <div class="card">
            <div class="visualizer">
                <canvas id="waveCanvas"></canvas>
            </div>
        </div>

        <div class="card">
            <div style="text-align: center; margin-bottom: 10px; color: #888; font-size: 12px;">WALLET BALANCE</div>
            <div class="balance-amount" id="balanceAmount">LOADING...</div>
        </div>

        <div class="card">
            <div class="info-grid">
                <div class="info-row">
                    <span class="info-label">WALLET</span>
                    <span class="info-value">{{ buyer_address[:20] }}...</span>
                </div>
                <div class="info-row">
                    <span class="info-label">NET</span>
                    <span class="info-value">BASE_SEPOLIA</span>
                </div>
            </div>
        </div>

        <div class="payment-box" id="paymentBox">
            <div class="payment-label">INCOMING REQUEST</div>
            <div class="payment-amount" id="paymentAmount">0.000</div>
            <div class="payment-label" id="paymentSeller" style="margin-top: 5px;">FROM: 0x...</div>
        </div>

        <div class="success-box" id="successBox">
            <div class="success-title">PAYMENT TRANSMITTED</div>
        </div>

        <button class="btn" id="startBtn" onclick="startListening()">
            ACTIVATE LISTENER
        </button>
        <button class="btn" id="resetBtn" onclick="resetDemo()" style="display: none;">
            RESET SYSTEM
        </button>
    </div>

    <script>
        let polling = null;
        let balancePolling = null;
        let lastBalance = null;
        
        // Visualizer
        const canvas = document.getElementById('waveCanvas');
        const ctx = canvas.getContext('2d');
        let currentStatus = 'idle';
        
        // Bit buffer for visualization
        const bitCount = 50;
        const bits = new Array(bitCount).fill(0);
        let frameCount = 0;

        function resizeCanvas() {
            canvas.width = canvas.offsetWidth;
            canvas.height = canvas.offsetHeight;
        }
        window.addEventListener('resize', resizeCanvas);
        resizeCanvas();

        function drawWave() {
            frameCount++;
            
            if (frameCount % 2 === 0) {
                bits.shift();
                const amp = window.currentAmplitude || 0;
                
                if (currentStatus === 'listening') {
                    // React to mic input
                    bits.push(amp > 0.05 ? 1 : 0);
                } else if (currentStatus === 'playing') {
                    // Simulated output
                    bits.push(Math.random() > 0.5 ? 1 : 0);
                } else {
                    bits.push(0);
                }
            }

            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            ctx.lineWidth = 2;
            // Use cyan for buyer
            ctx.strokeStyle = currentStatus === 'idle' ? '#333' : '#0ff';
            ctx.beginPath();
            
            const width = canvas.width;
            const height = canvas.height;
            const step = width / bitCount;
            
            const highY = height * 0.2;
            const lowY = height * 0.8;
            
            ctx.moveTo(0, bits[0] ? highY : lowY);
            
            for (let i = 0; i < bitCount; i++) {
                const x = i * step;
                const y = bits[i] ? highY : lowY;
                
                // Draw square wave
                ctx.lineTo(x, y);
                ctx.lineTo(x + step, y);
            }
            
            ctx.stroke();
            requestAnimationFrame(drawWave);
        }
        drawWave();

        window.onload = () => {
            updateBalance();
            balancePolling = setInterval(updateBalance, 5000);
        };

        async function updateBalance() {
            try {
                const resp = await fetch('/balance');
                const data = await resp.json();
                const balanceEl = document.getElementById('balanceAmount');
                const newBalance = data.balance.toFixed(6);
                
                balanceEl.textContent = newBalance + ' USDC';
                lastBalance = newBalance;
            } catch (e) {
                console.error('Balance error:', e);
            }
        }

        async function startListening() {
            document.getElementById('startBtn').disabled = true;
            document.getElementById('startBtn').textContent = 'LISTENING...';
            
            const resp = await fetch('/start', { method: 'POST' });
            polling = setInterval(updateStatus, 500);
        }

        async function updateStatus() {
            const resp = await fetch('/status');
            const data = await resp.json();
            
            window.currentAmplitude = data.amplitude;
            
            document.getElementById('statusText').textContent = data.message.toUpperCase();
            currentStatus = data.status;
            
            const dot = document.getElementById('statusDot');
            dot.className = 'status-dot ' + data.status;
            
            // Update steps
            for (let i = 1; i <= 3; i++) {
                const step = document.getElementById('step' + i);
                step.className = 'step';
                if (i < data.step) step.classList.add('done');
                if (i === data.step) step.classList.add('active');
            }
            
            // Show payment box when request decoded
            if (data.request_decoded && data.price) {
                document.getElementById('paymentBox').style.display = 'block';
                document.getElementById('paymentAmount').textContent = (data.price / 1000000).toFixed(3) + ' USDC';
                document.getElementById('paymentSeller').textContent = 'DEST: ' + data.seller.slice(0, 20) + '...';
            }
            
            if (data.payment_sent) {
                clearInterval(polling);
                document.getElementById('paymentBox').style.display = 'none';
                document.getElementById('successBox').style.display = 'block';
                document.getElementById('startBtn').style.display = 'none';
                document.getElementById('resetBtn').style.display = 'block';
                setTimeout(updateBalance, 1000);
                setTimeout(updateBalance, 3000);
            }
            
            if (data.status === 'error') {
                clearInterval(polling);
                document.getElementById('startBtn').disabled = false;
                document.getElementById('startBtn').textContent = 'RETRY CONNECTION';
            }
        }

        async function resetDemo() {
            await fetch('/reset', { method: 'POST' });
            document.getElementById('paymentBox').style.display = 'none';
            document.getElementById('successBox').style.display = 'none';
            document.getElementById('startBtn').style.display = 'block';
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').textContent = 'ACTIVATE LISTENER';
            document.getElementById('resetBtn').style.display = 'none';
            document.getElementById('statusDot').className = 'status-dot idle';
            document.getElementById('statusText').textContent = 'SYSTEM IDLE';
            currentStatus = 'idle';
            for (let i = 1; i <= 3; i++) {
                document.getElementById('step' + i).className = 'step';
            }
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    private_key = os.getenv("BUYER_PRIVATE_KEY")
    account = Account.from_key(private_key)
    return render_template_string(HTML_TEMPLATE, buyer_address=account.address)

@app.route('/status')
def get_status():
    return jsonify(state)

@app.route('/balance')
def get_balance():
    private_key = os.getenv("BUYER_PRIVATE_KEY")
    account = Account.from_key(private_key)
    balance = get_usdc_balance(account.address)
    return jsonify({"balance": balance, "address": account.address})

@app.route('/reset', methods=['POST'])
def reset():
    global state
    state = {
        "status": "idle",
        "message": "Ready to listen",
        "step": 0,
        "request_decoded": False,
        "payment_sent": False,
        "price": None,
        "seller": None
    }
    return jsonify({"ok": True})

@app.route('/start', methods=['POST'])
def start():
    global state
    # Reset state immediately before starting thread
    state = {
        "status": "listening",
        "message": "🎤 Starting...",
        "step": 1,
        "request_decoded": False,
        "payment_sent": False,
        "price": None,
        "seller": None
    }
    print(f"[DEBUG] /start called, state reset")
    thread = threading.Thread(target=run_buyer_flow)
    thread.start()
    return jsonify({"ok": True})

def run_buyer_flow():
    global state
    
    print("\n" + "="*50)
    print("[DEBUG] run_buyer_flow() STARTED")
    print("="*50)
    
    # Reset state at start
    state["status"] = "listening"
    state["step"] = 1
    state["request_decoded"] = False
    state["payment_sent"] = False
    
    try:
        private_key = os.getenv("BUYER_PRIVATE_KEY")
        account = Account.from_key(private_key)
        
        # Step 1: Listen for payment request
        state["message"] = "🎤 Listening for payment request..."
        print(f"[DEBUG] State set to listening")
        
        request_duration = get_duration(54) + 8  # 54 bytes + generous buffer
        print(f"[DEBUG] Will record for {request_duration:.1f} seconds...")
        
        try:
            # Use InputStream for real-time amplitude updates
            recording_buffer = []
            
            def audio_callback(indata, frames, time, status):
                if status:
                    print(status)
                state["amplitude"] = float(np.max(np.abs(indata)))
                recording_buffer.append(indata.copy())
                
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback):
                sd.sleep(int(request_duration * 1000))
                
            state["amplitude"] = 0.0
            
            audio_data = np.concatenate(recording_buffer, axis=0).flatten()
            print(f"[DEBUG] Recording complete. Got {len(audio_data)} samples")
        except Exception as e:
            state["status"] = "error"
            state["message"] = f"❌ Recording error: {str(e)}"
            return
        
        # Save for debugging
        audio_int16 = (audio_data * 32767).astype('int16')
        wav.write("received_request.wav", SAMPLE_RATE, audio_int16)
        
        # Decode
        state["message"] = "⏳ Decoding payment request..."
        
        # Check if we got any signal
        max_amplitude = np.max(np.abs(audio_data))
        print(f"[DEBUG] Recording max amplitude: {max_amplitude:.4f}")
        
        if max_amplitude < 0.01:
            state["status"] = "error"
            state["message"] = "❌ No audio detected. Make sure seller is playing!"
            return
        
        request_bytes = decode_fsk(audio_data)
        
        if not request_bytes:
            state["status"] = "error"
            state["message"] = f"❌ Failed to decode (amp={max_amplitude:.2f}). Check timing."
            return
        
        request = CompactPaymentRequest.from_bytes(request_bytes)
        state["request_decoded"] = True
        state["price"] = request.price
        state["seller"] = request.pay_to
        state["message"] = f"📝 Received: ${request.price/1000000:.3f} USDC"
        
        # Step 2: Sign payment
        state["step"] = 2
        state["status"] = "signing"
        time.sleep(1)
        state["message"] = "✍️ Signing payment authorization..."
        
        # Create payment using x402
        from x402.clients.httpx import x402Client
        from x402.types import PaymentRequirements
        
        reconstructed_402 = request.to_402_response()
        x402_client = x402Client(account)
        accepts = [PaymentRequirements(**a) for a in reconstructed_402['accepts']]
        selected = x402_client.select_payment_requirements(accepts)
        payment_header = x402_client.create_payment_header(selected)
        
        # Convert to compact
        compact_response = CompactPaymentResponse.from_x_payment_header(payment_header)
        response_bytes = compact_response.to_bytes()
        
        state["message"] = "✅ Payment signed!"
        time.sleep(1)
        
        # Step 3: Send response
        state["step"] = 3
        state["status"] = "playing"
        state["message"] = "🔊 Sending payment response..."
        
        response_audio = encode_fsk(response_bytes)
        
        # Save for debugging
        audio_int16 = (response_audio * 32767).astype('int16')
        wav.write("payment_response.wav", SAMPLE_RATE, audio_int16)
        
        # Play
        sd.play(response_audio, SAMPLE_RATE)
        sd.wait()
        
        state["status"] = "success"
        state["message"] = "✅ Payment response sent!"
        state["payment_sent"] = True
        
    except Exception as e:
        state["status"] = "error"
        state["message"] = f"❌ Error: {str(e)}"

if __name__ == "__main__":
    private_key = os.getenv("BUYER_PRIVATE_KEY")
    if not private_key:
        print("ERROR: Set BUYER_PRIVATE_KEY in .env")
        exit(1)
    
    account = Account.from_key(private_key)
    
    print("\n" + "="*50)
    print("  x402 BUYER UI")
    print("="*50)
    print(f"\n  Open: http://localhost:5002")
    print(f"  Wallet: {account.address[:30]}...")
    print("\n  Click 'Listen' when seller starts!")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=5002, debug=False)

