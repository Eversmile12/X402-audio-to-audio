"""
OOK (On-Off Keying) modem for transmitting 32-byte hashes over audio.

OOK encodes bits as presence/absence of a tone:
- Bit 1 → tone (2400 Hz)
- Bit 0 → silence

Much more robust than FSK for poor acoustic channels.

Uses 2x repetition coding for speed with decent robustness.

Protocol:
1. Preamble: alternating tone/silence for sync
2. Sync pattern: specific tone pattern to mark start
3. Length byte
4. Payload - each bit repeated 3x
5. CRC-16 checksum - each bit repeated 3x
"""

import numpy as np
from scipy import signal

# OOK Parameters - FAST MODE for compact x402
SAMPLE_RATE = 48000
TONE_FREQ = 2400  # Hz - single tone for "1" bits
BIT_DURATION = 0.010  # 10ms per bit (100 baud)
SAMPLES_PER_BIT = int(SAMPLE_RATE * BIT_DURATION)
REPETITIONS = 2  # 2x for speed with decent reliability

# Amplitude threshold for detecting "tone present"
DETECTION_THRESHOLD = 0.15


def crc16(data: bytes) -> int:
    """Calculate CRC-16-CCITT checksum."""
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc


def bytes_to_bits(data: bytes) -> list:
    """Convert bytes to list of bits (MSB first)."""
    bits = []
    for byte in data:
        for i in range(7, -1, -1):
            bits.append((byte >> i) & 1)
    return bits


def bits_to_bytes(bits: list) -> bytes:
    """Convert list of bits back to bytes."""
    while len(bits) % 8 != 0:
        bits.append(0)
    
    result = []
    for i in range(0, len(bits), 8):
        byte = 0
        for j in range(8):
            byte = (byte << 1) | bits[i + j]
        result.append(byte)
    return bytes(result)


def generate_tone(num_samples: int) -> np.ndarray:
    """Generate a sine wave tone."""
    t = np.arange(num_samples) / SAMPLE_RATE
    return np.sin(2 * np.pi * TONE_FREQ * t) * 0.8


def goertzel_power(samples: np.ndarray, target_freq: float = TONE_FREQ) -> float:
    """
    Compute power at a specific frequency using Goertzel algorithm.
    
    This is much more precise than envelope detection - it specifically
    measures energy at exactly 2400Hz, rejecting noise at other frequencies.
    """
    n = len(samples)
    if n == 0:
        return 0.0
    
    # Calculate the bin index for our target frequency
    k = int(0.5 + (n * target_freq) / SAMPLE_RATE)
    omega = (2.0 * np.pi * k) / n
    coeff = 2.0 * np.cos(omega)
    
    # Goertzel iteration
    s0, s1, s2 = 0.0, 0.0, 0.0
    for sample in samples:
        s0 = sample + coeff * s1 - s2
        s2 = s1
        s1 = s0
    
    # Calculate power (magnitude squared)
    power = s1 * s1 + s2 * s2 - coeff * s1 * s2
    
    # Normalize by number of samples
    return power / (n * n)


def generate_silence(num_samples: int) -> np.ndarray:
    """Generate silence."""
    return np.zeros(num_samples)


def encode_fsk(data: bytes) -> np.ndarray:
    """
    Encode bytes into OOK audio signal with repetition coding.
    
    Returns float32 audio samples at SAMPLE_RATE.
    """
    # Build packet
    length_byte = bytes([len(data)])
    crc = crc16(data)
    crc_bytes = bytes([crc >> 8, crc & 0xFF])
    
    # Preamble: alternating 1010... pattern (4 bytes)
    preamble = bytes([0xAA] * 4)
    # Sync byte: 0x55 marks end of preamble
    sync = bytes([0x55])
    
    header = preamble + sync
    header_bits = bytes_to_bits(header)
    
    # Length byte gets repetition too (it was vulnerable to corruption)
    length_bits = bytes_to_bits(length_byte)
    
    # Payload + CRC
    payload_data = data + crc_bytes
    payload_bits = bytes_to_bits(payload_data)
    
    # Generate OOK waveform
    samples = []
    
    # Encode header (preamble + sync, no repetition for sync detection)
    for bit in header_bits:
        if bit:
            samples.extend(generate_tone(SAMPLES_PER_BIT))
        else:
            samples.extend(generate_silence(SAMPLES_PER_BIT))
    
    # Encode length byte with repetition
    for bit in length_bits:
        for _ in range(REPETITIONS):
            if bit:
                samples.extend(generate_tone(SAMPLES_PER_BIT))
            else:
                samples.extend(generate_silence(SAMPLES_PER_BIT))
    
    # Encode payload with repetition
    for bit in payload_bits:
        for _ in range(REPETITIONS):
            if bit:
                samples.extend(generate_tone(SAMPLES_PER_BIT))
            else:
                samples.extend(generate_silence(SAMPLES_PER_BIT))
    
    # Add silence at start/end
    silence = np.zeros(int(SAMPLE_RATE * 0.2))
    audio = np.concatenate([silence, np.array(samples), silence])
    
    return audio.astype(np.float32)


def decode_fsk(audio: np.ndarray) -> bytes | None:
    """
    Decode OOK audio signal with repetition coding back to bytes.
    
    Uses Goertzel algorithm for precise 2400Hz tone detection,
    which is much more robust against environmental noise.
    
    Returns the decoded payload, or None if decoding fails.
    """
    # Tight bandpass filter around 2400Hz (±400Hz = 2000-2800Hz)
    # Rejects voice frequencies while giving headroom for noise
    nyquist = SAMPLE_RATE / 2
    low = (TONE_FREQ - 400) / nyquist   # 2000 Hz
    high = (TONE_FREQ + 400) / nyquist  # 2800 Hz
    b, a = signal.butter(4, [low, high], btype='band')  # 4th order for sharper rolloff
    filtered = signal.filtfilt(b, a, audio)
    
    # Calculate Goertzel power for each bit-sized window
    # This specifically measures energy at exactly 2400Hz
    window_powers = []
    for i in range(0, len(filtered) - SAMPLES_PER_BIT, SAMPLES_PER_BIT):
        chunk = filtered[i:i + SAMPLES_PER_BIT]
        power = goertzel_power(chunk)
        window_powers.append(power)
    
    if len(window_powers) < 10:
        return None  # Not enough data
    
    window_powers = np.array(window_powers)
    
    # Check if there's any signal at all
    max_power = np.max(window_powers)
    if max_power < 1e-8:
        return None  # No 2400Hz tone detected
    
    # Normalize powers
    normalized_powers = window_powers / max_power
    
    # Calculate adaptive threshold using percentiles
    # This handles varying signal levels and noise floors
    high_level = np.percentile(normalized_powers, 85)  # Typical "1" power
    low_level = np.percentile(normalized_powers, 15)   # Typical "0" power
    adaptive_threshold = (high_level + low_level) / 2
    
    def decode_bit(start_idx: int) -> int | None:
        """Decode a single bit using Goertzel power at 2400Hz."""
        end_idx = start_idx + SAMPLES_PER_BIT
        if end_idx > len(filtered):
            return None
        chunk = filtered[start_idx:end_idx]
        power = goertzel_power(chunk) / max_power  # Normalize
        return 1 if power > adaptive_threshold else 0
    
    def decode_byte_simple(start_idx: int) -> tuple[int | None, int]:
        """Decode one byte without repetition."""
        bits = []
        for i in range(8):
            bit = decode_bit(start_idx + i * SAMPLES_PER_BIT)
            if bit is None:
                return None, start_idx
            bits.append(bit)
        value = sum(bits[i] << (7-i) for i in range(8))
        return value, start_idx + 8 * SAMPLES_PER_BIT
    
    def decode_bit_with_repetition(start_idx: int) -> tuple[int | None, int]:
        """Decode one bit using majority vote over REPETITIONS samples."""
        votes = []
        pos = start_idx
        for _ in range(REPETITIONS):
            bit = decode_bit(pos)
            if bit is None:
                return None, start_idx
            votes.append(bit)
            pos += SAMPLES_PER_BIT
        result = 1 if sum(votes) > REPETITIONS // 2 else 0
        return result, pos
    
    def decode_byte_with_repetition(start_idx: int) -> tuple[int | None, int]:
        """Decode one byte with repetition coding."""
        bits = []
        pos = start_idx
        for _ in range(8):
            bit, pos = decode_bit_with_repetition(pos)
            if bit is None:
                return None, start_idx
            bits.append(bit)
        value = sum(bits[i] << (7-i) for i in range(8))
        return value, pos
    
    # === Find sync: scan for 0xAA -> 0x55 transition ===
    # Scan through audio looking for the preamble pattern
    # Use smaller step for better alignment (1/4 bit period)
    step = SAMPLES_PER_BIT // 4
    best_sync_pos = None
    
    # Start from beginning, scan up to 10 seconds
    max_search = min(len(filtered) - SAMPLES_PER_BIT * 60, int(SAMPLE_RATE * 10))
    
    for pos in range(0, max_search, step):
        byte1, next_pos = decode_byte_simple(pos)
        
        # Look for 0xAA (preamble byte)
        if byte1 == 0xAA:
            # Check if followed by another 0xAA or 0x55
            byte2, after_2 = decode_byte_simple(next_pos)
            
            if byte2 == 0x55:
                # Found AA 55 - this is our sync point
                best_sync_pos = next_pos
                break
            elif byte2 == 0xAA:
                # Might be in middle of preamble, keep scanning for 55
                byte3, after_3 = decode_byte_simple(after_2)
                if byte3 == 0x55:
                    best_sync_pos = after_2
                    break
                elif byte3 == 0xAA:
                    byte4, after_4 = decode_byte_simple(after_3)
                    if byte4 == 0x55:
                        best_sync_pos = after_3
                        break
    
    if best_sync_pos is None:
        return None
    
    # Skip sync byte (0x55)
    decode_start = best_sync_pos + 8 * SAMPLES_PER_BIT
    
    # Decode length byte (WITH repetition for robustness)
    payload_length, decode_start = decode_byte_with_repetition(decode_start)
    if payload_length is None or payload_length > 255:
        return None
    
    # Decode payload + CRC with repetition coding
    payload_bytes = []
    for _ in range(payload_length + 2):
        byte_val, decode_start = decode_byte_with_repetition(decode_start)
        if byte_val is None:
            return None
        payload_bytes.append(byte_val)
    
    payload = bytes(payload_bytes[:payload_length])
    received_crc = (payload_bytes[payload_length] << 8) | payload_bytes[payload_length + 1]
    
    # Verify CRC
    calculated_crc = crc16(payload)
    if received_crc != calculated_crc:
        return None
    
    return payload


def get_duration(data_length: int) -> float:
    """Calculate audio duration for given payload length."""
    header_bits = (4 + 1) * 8  # preamble + sync (no repetition)
    length_bits = 8 * REPETITIONS  # length byte (with repetition)
    payload_bits = (data_length + 2) * 8 * REPETITIONS  # data + crc (with repetition)
    total_bits = header_bits + length_bits + payload_bits
    return total_bits * BIT_DURATION + 0.4
