"""
Camera feed streamer for Louise drone escort system.

Captures frames from the drone's onboard camera (USB, CSI, or IP stream)
and POSTs them to the Louise server for Helpstral/Flystral vision analysis.

Usage:
  # USB camera (default /dev/video0)
  python camera_stream.py --server http://localhost:8000

  # Specific device index
  python camera_stream.py --server http://localhost:8000 --device 0

  # RTSP stream from IP camera
  python camera_stream.py --server http://localhost:8000 --device rtsp://192.168.1.100:8554/stream

  # Adjust frame rate (default 2 fps — matches 5s agent loop)
  python camera_stream.py --server http://localhost:8000 --fps 4

Requirements:
  pip install opencv-python requests
"""

from __future__ import annotations

import argparse
import base64
import sys
import time

try:
    import cv2
except ImportError:
    print("pip install opencv-python", file=sys.stderr)
    sys.exit(1)

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Stream camera frames to Louise server")
    parser.add_argument("--server", default="http://localhost:8000", help="Louise server URL")
    parser.add_argument("--device", default="0", help="Camera device index or RTSP URL")
    parser.add_argument("--fps", type=float, default=2.0, help="Frames per second to send")
    parser.add_argument("--width", type=int, default=640, help="Frame width")
    parser.add_argument("--height", type=int, default=480, help="Frame height")
    parser.add_argument("--quality", type=int, default=70, help="JPEG quality (1-100)")
    args = parser.parse_args()

    device = int(args.device) if args.device.isdigit() else args.device
    cap = cv2.VideoCapture(device)
    if not cap.isOpened():
        print(f"Failed to open camera: {args.device}", file=sys.stderr)
        sys.exit(1)

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)

    endpoint = f"{args.server.rstrip('/')}/api/camera/frame"
    interval = 1.0 / args.fps
    frame_count = 0
    error_count = 0

    print(f"Streaming from {args.device} -> {endpoint} at {args.fps} fps")
    print(f"Resolution: {args.width}x{args.height}, JPEG quality: {args.quality}")

    try:
        while True:
            t0 = time.time()

            ret, frame = cap.read()
            if not ret:
                print("Failed to capture frame, retrying...", file=sys.stderr)
                time.sleep(1)
                error_count += 1
                if error_count > 10:
                    print("Too many capture failures, exiting", file=sys.stderr)
                    break
                continue

            _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, args.quality])
            b64 = base64.b64encode(buf).decode()

            try:
                resp = requests.post(endpoint, json={"image_b64": b64}, timeout=5)
                if resp.status_code == 200:
                    frame_count += 1
                    if frame_count % 10 == 0:
                        print(f"Sent {frame_count} frames ({len(b64)} bytes/frame)")
                    error_count = 0
                else:
                    print(f"Server returned {resp.status_code}", file=sys.stderr)
            except requests.RequestException as e:
                error_count += 1
                print(f"Send failed: {e}", file=sys.stderr)
                if error_count > 30:
                    print("Too many send failures, exiting", file=sys.stderr)
                    break

            elapsed = time.time() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)

    except KeyboardInterrupt:
        print(f"\nStopped. Sent {frame_count} frames total.")
    finally:
        cap.release()


if __name__ == "__main__":
    main()
