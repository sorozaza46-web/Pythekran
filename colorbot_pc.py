import socket
import time
import math
import random
import bettercam
import cv2
import numpy as np
import win32api  # Windows tuş girdilerini okumak için

# --- AYARLAR ---
AIM_KEY = 0x56  # 'V' Tuşunun Sanal Kodu (Virtual-Key Code)

# TELEFON TCP BAĞLANTI AYARLARI
TELEFON_IP = "192.168.1.35"  # Telefonun Wi-Fi IP adresi
TARGET_PORT = 9999           # Telefondaki TCP dinleyici portu

def is_aim_key_pressed():
    """V tuşuna basılı tutulup tutulmadığını kontrol eder"""
    return win32api.GetAsyncKeyState(AIM_KEY) < 0


class HumanMouseEngine:
    def __init__(self):
        self.last_dx = 0
        self.last_dy = 0

    def calculate_human_movement(self, dx, dy):
        distance = math.hypot(dx, dy)
        if distance == 0:
            return 0, 0

        # Mesafe Bazlı Dinamik İvme
        speed_factor = 0.15 + (0.35 * (1.0 - math.exp(-distance / 35.0)))

        # Overshoot (Aşma ve Düzeltme) İhtimali
        overshoot_x, overshoot_y = 0, 0
        if distance > 40 and random.random() < 0.20:
            overshoot_x = dx * random.uniform(0.02, 0.05)
            overshoot_y = dy * random.uniform(0.02, 0.05)

        target_x = (dx + overshoot_x) * speed_factor
        target_y = (dy + overshoot_y) * speed_factor

        # Dik Eksenli Kas Titremesi (Perpendicular Jitter)
        jitter_intensity = max(0.2, min(1.2, distance * 0.02))
        perp_x = -dy / distance if distance > 0 else 0
        perp_y = dx / distance if distance > 0 else 0
        
        jitter_val = random.gauss(0, jitter_intensity)
        jitter_x = perp_x * jitter_val
        jitter_y = perp_y * jitter_val

        # Atalet (Inertia)
        final_x = target_x + jitter_x + (self.last_dx * 0.08)
        final_y = target_y + jitter_y + (self.last_dy * 0.08)

        self.last_dx = final_x
        self.last_dy = final_y

        return int(final_x), int(final_y)


def main():
    print(f"[*] TCP Colorbot Başlatılıyor...")
    print(f"[*] Aktif Tuş: 'V' Tuşu")
    print(f"[*] Bağlanılan Hedef (TCP): {TELEFON_IP}:{TARGET_PORT}")

    # TCP SOKET OLUŞTURMA VE BAĞLANMA (SOCK_STREAM)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1) # Gecikmeyi sıfırlamak için Nagle algoritmasını kapatır

    try:
        sock.connect((TELEFON_IP, TARGET_PORT))
        print("[+] Telefondaki TCP Sunucusuna Başarıyla Bağlanıldı!")
    except Exception as e:
        print(f"[-] TCP Bağlantı Hatası: {e}")
        print("[-] Lütfen telefondaki TCP sunucusunun açık ve IP/Port bilgilerinin doğru olduğunu kontrol edin.")
        return

    mouse_engine = HumanMouseEngine()

    try:
        camera = bettercam.create(output_color="BGR")
    except Exception as e:
        print(f"[-] Kamera başlatılamadı: {e}")
        sock.close()
        return

    base_fov = 140
    screen_w, screen_h = 1920, 1080
    center_x = base_fov // 2
    center_y = base_fov // 2

    LOWER_PURPLE = np.array([142, 115, 135], dtype=np.uint8)
    UPPER_PURPLE = np.array([153, 255, 255], dtype=np.uint8)

    camera.start(region=((screen_w - base_fov)//2, (screen_h - base_fov)//2, 
                        (screen_w + base_fov)//2, (screen_h + base_fov)//2), 
                 target_fps=240)

    target_detected_time = None
    REACTION_DELAY = random.uniform(0.12, 0.18)

    try:
        while True:
            # V TUŞU KONTROLÜ
            if not is_aim_key_pressed():
                target_detected_time = None
                mouse_engine.last_dx = 0
                mouse_engine.last_dy = 0
                time.sleep(0.005)
                continue

            frame = camera.get_latest_frame()
            if frame is None:
                continue

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)

            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

            M = cv2.moments(mask, binaryImage=True)
            if M["m00"] > 60:
                if target_detected_time is None:
                    target_detected_time = time.time()

                if time.time() - target_detected_time < REACTION_DELAY:
                    continue

                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])

                raw_dx = cx - center_x
                raw_dy = cy - center_y

                dx, dy = mouse_engine.calculate_human_movement(raw_dx, raw_dy)

                dx = max(-127, min(127, dx))
                dy = max(-127, min(127, dy))

                if dx != 0 or dy != 0:
                    # TCP PROTOKOL FORMATI: "MOUSE dx dy\n"
                    payload = f"MOUSE {dx} {dy}\n".encode('utf-8')
                    sock.sendall(payload)
                    time.sleep(random.uniform(0.0011, 0.0022))

            else:
                target_detected_time = None
                REACTION_DELAY = random.uniform(0.12, 0.18)
                mouse_engine.last_dx = 0
                mouse_engine.last_dy = 0

    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"[-] Veri gönderim hatası: {e}")
    finally:
        camera.stop()
        sock.close()

if __name__ == "__main__":
    main()
    
