#!/usr/bin/env python3
"""Host side of the repro. For each try: reset the board over USB, write a newline at once (while
the sketch is still waiting to call Serial.begin()), then send PING and wait for PONG.

    python host.py <port> [--tries 5]

The reset is the one esptool's USB Serial/JTAG reset and most serial tools do on connect: DTR and RTS
toggled while the port is open. The early write stands in for any host that talks first: a test
runner flushing the line, a tool probing for a bootloader, a terminal sending a keystroke.

Exit status 0 when every try got a PONG, 1 otherwise.
"""
import argparse
import sys
import time

import serial

BOOT_TIMEOUT = 10  # seconds from reset to the sketch's BOOT line
PONG_TIMEOUT = 5   # seconds from the first PING to its PONG


def log(start, text):
    print(f"  {time.time() - start:6.2f} {text}", flush=True)


def one_try(port, early_write):
    """Return "PASS", or why the try failed."""
    ser = serial.Serial(port, 115200, timeout=0.1, write_timeout=2)
    start = time.time()
    try:
        # Reset into the sketch: RTS=1/DTR=0 holds the chip in reset, DTR=1 releases it.
        ser.dtr = False
        ser.rts = False
        time.sleep(0.1)
        ser.dtr = True
        ser.rts = True
        ser.reset_input_buffer()
        if early_write:
            ser.write(b"\n")
            log(start, '> "\\n" (early write, before Serial.begin())')

        buf = b""
        booted = False
        deadline = time.time() + BOOT_TIMEOUT
        next_ping = 0
        while time.time() < deadline:
            buf += ser.read(ser.in_waiting or 1)
            while b"\n" in buf:
                raw, buf = buf.split(b"\n", 1)
                text = raw.decode(errors="replace").rstrip()
                log(start, f"< {text}")
                if text.startswith("BOOT"):
                    booted = True
                    deadline = time.time() + PONG_TIMEOUT
                    next_ping = time.time()
                elif text == "PONG":
                    return "PASS"
            if booted and time.time() >= next_ping:
                next_ping = time.time() + 1
                try:
                    ser.write(b"PING\n")
                    log(start, "> PING")
                except serial.SerialTimeoutException:
                    log(start, "> PING (write timed out: the device is not accepting data)")
        return "FAIL: no PONG (the device is not reading host data)" if booted else "FAIL: no BOOT line"
    finally:
        # Drop any PING the device never took, or close() waits for it to drain (forever, on macOS).
        ser.reset_output_buffer()
        ser.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("port", help="the board's native USB port, e.g. /dev/cu.usbmodem1101 or COM5")
    ap.add_argument("--tries", type=int, default=5)
    ap.add_argument("--no-early-write", dest="early_write", action="store_false",
                    help="control run: write nothing until the sketch has booted")
    a = ap.parse_args()

    results = []
    for n in range(1, a.tries + 1):
        print(f"try {n}/{a.tries}", flush=True)
        result = one_try(a.port, a.early_write)
        print(f"  {result}", flush=True)
        results.append(result)
    passed = results.count("PASS")
    print(f"RESULT early_write={a.early_write} passed={passed}/{a.tries}")
    sys.exit(0 if passed == a.tries else 1)


if __name__ == "__main__":
    main()
