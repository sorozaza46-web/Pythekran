import socket
import struct
import time
import bettercam
import cv2
import numpy as np

def main():
    print("[+] Colorbot PC Başlatılıyor...")
    
    # UDP Soket Yapılandırması (Telefona Veri Gönderimi)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    target_addr = ('127.0.0.1', 12345)

    # DXGI Ekran Yakalama (DirectX Donanım Hızlandırma)
    try:
        camera = bettercam.create(output_color="BGR")
    except Exception as e:
        print(f"[-] Ekran sürücüsü başlatılamadı: {e}")
        return

    # FOV Ayarları (Ekran Ortası 200x200)
    screen_w, screen_h = 1920, 1080
    fov = 200
    left = (screen_w - fov) // 2
    top = (screen_h - fov) // 2
    region = (left, top, left + fov, top + fov)
    center = fov // 2

    # Renk Filtresi (Mor / Pembe Düşman Rengi)
    LOWER_PURPLE = np.array([140, 120, 150], dtype=np.uint8)
    UPPER_PURPLE = np.array([150, 255, 255], dtype=np.uint8)

    camera.start(region=region, target_fps=240)
    print("[+] Tarama aktif (240 FPS Target). Çıkış için Ctrl+C.")

    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is None:
                continue

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)

            M = cv2.moments(mask, binaryImage=True)
            if M["m00"] > 0:
                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])

                # Sapma ve Yumuşatma (Smooth)
                dx = int((cx - center) * 0.35)
                dy = int((cy - center) * 0.35)

                # Byte Sınırları (-127 ile 127 arası)
                dx = max(-127, min(127, dx))
                dy = max(-127, min(127, dy))

                if dx != 0 or dy != 0:
                    sock.sendto(struct.pack('bb', dx, dy), target_addr)

    except KeyboardInterrupt:
        print("\n[-] Kapatılıyor...")
    finally:
        camera.stop()
        sock.close()

if __name__ == "__main__":
    main()
  
