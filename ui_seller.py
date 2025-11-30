#!/usr/bin/env python3
"""
Audio Seller - Web UI
Run this on the SELLER device.
"""

import os
import time
import threading
from flask import Flask, render_template_string, jsonify, request
import numpy as np
import sounddevice as sd
import scipy.io.wavfile as wav
from dotenv import load_dotenv

from fsk_modem import encode_fsk, decode_fsk, SAMPLE_RATE, get_duration
from payment import PaymentRequest, PaymentResponse
from facilitator import settle_payment, SettlementRequest
from config import get_usdc_balance

load_dotenv()

app = Flask(__name__)

# Global state
state = {
    "status": "idle",
    "message": "Ready to start",
    "step": 0,
    "request": None,
    "verified": False,
    "secret": None,
    "amplitude": 0.0  # Add amplitude for visualizer
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>x402 Seller</title>
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
            color: #0f0;
            padding: 40px 20px;
            text-shadow: 0 0 5px rgba(0, 255, 0, 0.5);
        }
        .container {
            max-width: 700px;
            margin: 0 auto;
            border: 1px solid #0f0;
            padding: 20px;
            box-shadow: 0 0 20px rgba(0, 255, 0, 0.2);
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
            color: #0f0;
        }
        .header {
            text-align: center;
            margin-bottom: 40px;
            border-bottom: 1px dashed #0f0;
            padding-bottom: 20px;
        }
        .title {
            font-size: 48px;
            font-weight: 700;
            color: #0f0;
            letter-spacing: 2px;
            text-transform: uppercase;
            animation: glitch 5s infinite;
            position: relative;
        }
        @keyframes glitch {
            0%, 90% { transform: translate(0); text-shadow: none; }
            91% { transform: translate(2px,0) skew(0deg); text-shadow: -2px 0 #ff0000; }
            92% { transform: translate(-2px,0) skew(0deg); text-shadow: 2px 0 #0000ff; }
            93% { transform: translate(0,0) skew(5deg); text-shadow: none; }
            94% { transform: translate(0,0) skew(0deg); }
            100% { transform: translate(0); }
        }
        .subtitle {
            color: #0fa;
            margin-top: 8px;
            font-size: 16px;
            text-transform: uppercase;
            letter-spacing: 4px;
        }
        .role-badge {
            display: inline-block;
            border: 1px solid #0f0;
            color: #0f0;
            padding: 4px 12px;
            font-size: 14px;
            font-weight: 600;
            margin-top: 16px;
            text-transform: uppercase;
            background: rgba(0, 255, 0, 0.1);
        }
        .card {
            border: 1px solid #0f0;
            background: rgba(0, 20, 0, 0.3);
            padding: 20px;
            margin-bottom: 20px;
            position: relative;
        }
        .card::after {
            content: '';
            position: absolute;
            top: 0; left: 0; right: 0; bottom: 0;
            border: 1px solid rgba(0, 255, 0, 0.1);
            pointer-events: none;
        }
        .status-card {
            display: flex;
            align-items: center;
            gap: 16px;
            border-color: #0ff;
            color: #0ff;
        }
        .status-dot {
            width: 12px;
            height: 12px;
            background: #0ff;
            box-shadow: 0 0 10px #0ff;
        }
        .status-dot.idle { background: #555; box-shadow: none; }
        .status-dot.playing { background: #0f0; box-shadow: 0 0 10px #0f0; animation: blink 0.1s infinite; }
        .status-dot.listening { background: #ff0; box-shadow: 0 0 10px #ff0; animation: blink 0.5s infinite; }
        .status-dot.verifying { background: #f0f; box-shadow: 0 0 10px #f0f; }
        .status-dot.success { background: #0f0; box-shadow: 0 0 20px #0f0; }
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
        .info-value { color: #0f0; }
        
        .btn {
            width: 100%;
            padding: 20px;
            background: #000;
            border: 2px solid #0f0;
            color: #0f0;
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
            background: #0f0;
            color: #000;
            box-shadow: 0 0 20px #0f0;
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
        .step.active { color: #0ff; text-shadow: 0 0 5px #0ff; }
        .step.done { color: #0f0; }
        
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
            color: #0f0;
            text-align: center;
            text-shadow: 0 0 10px rgba(0, 255, 0, 0.5);
        }
        
        .success-box {
            border: 2px solid #0f0;
            padding: 20px;
            text-align: center;
            margin-top: 20px;
            background: rgba(0, 255, 0, 0.1);
        }
        .secret-box {
            background: #000;
            border: 1px solid #0f0;
            padding: 10px;
            margin-top: 10px;
            color: #0f0;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <div class="title">x402hz</div>
            <div class="subtitle">payments over audio v1</div>
            <div class="role-badge">SELLER_NODE</div>
        </div>

        <div class="steps">
            <div class="step" id="step1">[01] BROADCAST</div>
            <div class="step" id="step2">[02] LISTEN</div>
            <div class="step" id="step3">[03] VERIFY</div>
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
                    <span class="info-label">PRICE</span>
                    <span class="info-value">0.001 USDC</span>
                </div>
                <div class="info-row">
                    <span class="info-label">NET</span>
                    <span class="info-value">BASE_SEPOLIA</span>
                </div>
                <div class="info-row">
                    <span class="info-label">ADDR</span>
                    <span class="info-value">{{ seller_address[:20] }}...</span>
                </div>
            </div>
        </div>

        <div id="successBox" class="success-box" style="display: none;">
            <div style="font-size: 24px; margin-bottom: 10px;">PAYMENT VERIFIED</div>
            <div class="secret-box" id="secretValue"></div>
        </div>

        <button class="btn" id="startBtn" onclick="startDemo()">
            INITIATE REQUEST
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
            
            // Shift bits
            if (frameCount % 2 === 0) { // Faster update
                bits.shift();
                
                // Use real amplitude if available, otherwise idle noise
                // We get this from a global variable updated by updateStatus
                const amp = window.currentAmplitude || 0;
                
                if (currentStatus === 'listening') {
                    // React to mic input
                    // Threshold for logic 1 vs 0 visualization
                    bits.push(amp > 0.05 ? 1 : 0); 
                } else if (currentStatus === 'playing') {
                    // Simulated output pattern
                    bits.push(Math.random() > 0.5 ? 1 : 0);
                } else {
                    // Idle line
                    bits.push(0);
                }
            }

            ctx.fillStyle = '#000';
            ctx.fillRect(0, 0, canvas.width, canvas.height);
            
            ctx.lineWidth = 2;
            ctx.strokeStyle = currentStatus === 'idle' ? '#333' : '#0f0';
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

        async function startDemo() {
            document.getElementById('startBtn').disabled = true;
            document.getElementById('startBtn').textContent = 'PROCESSING...';
            
            const resp = await fetch('/start', { method: 'POST' });
            polling = setInterval(updateStatus, 500);
        }

        async function updateStatus() {
            const resp = await fetch('/status');
            const data = await resp.json();
            
            // Store amplitude globally for the visualizer
            window.currentAmplitude = data.amplitude;
            
            document.getElementById('statusText').textContent = data.message.toUpperCase();
            currentStatus = data.status;
            
            const dot = document.getElementById('statusDot');
            dot.className = 'status-dot ' + data.status;
            
            for (let i = 1; i <= 3; i++) {
                const step = document.getElementById('step' + i);
                step.className = 'step';
                if (i < data.step) step.classList.add('done');
                if (i === data.step) step.classList.add('active');
            }
            
            if (data.verified) {
                clearInterval(polling);
                document.getElementById('successBox').style.display = 'block';
                document.getElementById('secretValue').textContent = data.secret;
                document.getElementById('startBtn').style.display = 'none';
                document.getElementById('resetBtn').style.display = 'block';
                setTimeout(updateBalance, 1000);
                setTimeout(updateBalance, 3000);
            }
            
            if (data.status === 'error') {
                clearInterval(polling);
                document.getElementById('startBtn').disabled = false;
                document.getElementById('startBtn').textContent = 'RETRY';
            }
        }

        async function resetDemo() {
            await fetch('/reset', { method: 'POST' });
            document.getElementById('successBox').style.display = 'none';
            document.getElementById('startBtn').style.display = 'block';
            document.getElementById('startBtn').disabled = false;
            document.getElementById('startBtn').textContent = 'INITIATE REQUEST';
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
    seller_address = os.getenv("SELLER_ADDRESS", "0x...")
    return render_template_string(HTML_TEMPLATE, seller_address=seller_address)

@app.route('/status')
def get_status():
    return jsonify(state)

@app.route('/balance')
def get_balance():
    seller_address = os.getenv("SELLER_ADDRESS")
    balance = get_usdc_balance(seller_address)
    return jsonify({"balance": balance, "address": seller_address})

@app.route('/reset', methods=['POST'])
def reset():
    global state
    state = {
        "status": "idle",
        "message": "Ready to start",
        "step": 0,
        "request": None,
        "verified": False,
        "secret": None
    }
    return jsonify({"ok": True})

@app.route('/start', methods=['POST'])
def start():
    thread = threading.Thread(target=run_seller_flow)
    thread.start()
    return jsonify({"ok": True})

def run_seller_flow():
    global state
    
    try:
        seller_address = os.getenv("SELLER_ADDRESS")
        buyer_address = os.getenv("BUYER_ADDRESS")
        
        # Step 1: Create and play payment request
        state["step"] = 1
        state["status"] = "playing"
        state["message"] = "🔊 Broadcasting payment request..."
        
        request = PaymentRequest(
            pay_to=seller_address,
            price=1000,  # 0.001 USDC
            timeout=120,
            network="base-sepolia",
            nonce=int(time.time()) % 256,
        )
        state["request"] = request
        
        request_bytes = request.to_bytes()
        request_audio = encode_fsk(request_bytes)
        
        # Save for debugging
        audio_int16 = (request_audio * 32767).astype('int16')
        wav.write("payment_request.wav", SAMPLE_RATE, audio_int16)
        
        # Play
        time.sleep(1)  # Brief pause
        sd.play(request_audio, SAMPLE_RATE)
        sd.wait()
        
        # Step 2: Listen for response
        state["step"] = 2
        state["status"] = "listening"
        state["message"] = "🎤 Waiting for buyer to process..."
        
        time.sleep(8)  # Wait for buyer to decode + sign (needs ~5-7 seconds)
        
        state["message"] = "🎤 Listening for payment response..."
        
        response_duration = get_duration(108) + 5  # 108 bytes + buffer
        
        # Use InputStream callback to capture amplitude in real-time
        recording_buffer = []
        
        def audio_callback(indata, frames, time, status):
            if status:
                print(status)
            # Update global amplitude for UI
            state["amplitude"] = float(np.max(np.abs(indata)))
            recording_buffer.append(indata.copy())
            
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, callback=audio_callback):
            sd.sleep(int(response_duration * 1000))
            
        # Reset amplitude
        state["amplitude"] = 0.0
        
        # Combine buffer into single array
        audio_data = np.concatenate(recording_buffer, axis=0).flatten()
        
        # Save for debugging
        audio_int16 = (audio_data * 32767).astype('int16')
        wav.write("received_response.wav", SAMPLE_RATE, audio_int16)
        
        # Step 3: Decode and verify
        state["step"] = 3
        state["status"] = "verifying"
        state["message"] = "⏳ Verifying payment..."
        
        response_bytes = decode_fsk(audio_data)
        
        if not response_bytes:
            state["status"] = "error"
            state["message"] = "❌ Failed to decode response. Try again."
            return
        
        response = PaymentResponse.from_bytes(response_bytes)
        
        # Settle directly on-chain using our facilitator
        settlement_params = response.to_settlement_params(buyer_address, request)
        settlement_request = SettlementRequest(**settlement_params)
        
        try:
            tx_hash = settle_payment(settlement_request)
            state["status"] = "success"
            state["message"] = "✅ Payment settled on-chain!"
            state["verified"] = True
            state["secret"] = f"TX: {tx_hash[:16]}..."
            print(f"[SUCCESS] Settlement TX: https://sepolia.basescan.org/tx/{tx_hash}")
        except Exception as settle_error:
            state["status"] = "error"
            state["message"] = f"❌ Settlement failed: {str(settle_error)}"
            
    except Exception as e:
        state["status"] = "error"
        state["message"] = f"❌ Error: {str(e)}"

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  x402 SELLER UI")
    print("="*50)
    print(f"\n  Open: http://localhost:5001")
    print(f"  Seller: {os.getenv('SELLER_ADDRESS', 'Not set')[:30]}...")
    print("\n  Make sure server_x402.py is running!")
    print("="*50 + "\n")
    
    app.run(host='0.0.0.0', port=5001, debug=False)

