import socket
import time
import math
import random
import cv2
import numpy as np
import win32api
import mss  # Bettercam yerine bellek hatası vermeyen MSS kütüphanesi

# --- AYARLAR ---
AIM_KEY = 0x56  # 'V' Tuşu (Virtual-Key Code)

LISTEN_IP = "0.0.0.0"
LISTEN_PORT = 9999

def is_aim_key_pressed():
    return win32api.GetAsyncKeyState(AIM_KEY) < 0


class HumanMouseEngine:
    def __init__(self):
        self.last_dx = 0
        self.last_dy = 0

    def calculate_human_movement(self, dx, dy):
        distance = math.hypot(dx, dy)
        if distance == 0:
            return 0, 0

        speed_factor = 0.15 + (0.35 * (1.0 - math.exp(-distance / 35.0)))

        overshoot_x, overshoot_y = 0, 0
        if distance > 40 and random.random() < 0.20:
            overshoot_x = dx * random.uniform(0.02, 0.05)
            overshoot_y = dy * random.uniform(0.02, 0.05)

        target_x = (dx + overshoot_x) * speed_factor
        target_y = (dy + overshoot_y) * speed_factor

        jitter_intensity = max(0.2, min(1.2, distance * 0.02))
        perp_x = -dy / distance if distance > 0 else 0
        perp_y = dx / distance if distance > 0 else 0
        
        jitter_val = random.gauss(0, jitter_intensity)
        jitter_x = perp_x * jitter_val
        jitter_y = perp_y * jitter_val

        final_x = target_x + jitter_x + (self.last_dx * 0.08)
        final_y = target_y + jitter_y + (self.last_dy * 0.08)

        self.last_dx = final_x
        self.last_dy = final_y

        return int(final_x), int(final_y)


def get_pc_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main():
    pc_ip = get_pc_local_ip()
    print(f"[*] PC TCP Sunucusu Başlatılıyor...")
    print(f"[*] Mobil Uygulamaya Girilecek IP: {pc_ip}")
    print(f"[*] Mobil Uygulamaya Girilecek Port: {LISTEN_PORT}")

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((LISTEN_IP, LISTEN_PORT))
    server_socket.listen(1)

    print(f"\n[+] Telefonun bağlanması bekleniyor...")
    client_socket, client_address = server_socket.accept()
    client_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[+] Telefon Bağlandı: {client_address[0]}:{client_address[1]}")

    mouse_engine = HumanMouseEngine()

    base_fov = 140
    screen_w, screen_h = 1920, 1080
    center_x = base_fov // 2
    center_y = base_fov // 2

    # Tarama bölgesi alan (Region of Interest)
    monitor = {
        "top": (screen_h - base_fov) // 2,
        "left": (screen_w - base_fov) // 2,
        "width": base_fov,
        "height": base_fov
    }

    LOWER_PURPLE = np.array([142, 115, 135], dtype=np.uint8)
    UPPER_PURPLE = np.array([153, 255, 255], dtype=np.uint8)

    target_detected_time = None
    REACTION_DELAY = random.uniform(0.12, 0.18)

    # MSS Ekran Yakalama Başlatılıyor
    with mss.mss() as sct:
        try:
            while True:
                if not is_aim_key_pressed():
                    target_detected_time = None
                    mouse_engine.last_dx = 0
                    mouse_engine.last_dy = 0
                    time.sleep(0.005)
                    continue

                # Ekrana doğrudan erişim (BGRA formatı)
                sct_img = sct.grab(monitor)
                frame = np.array(sct_img)

                # BGRA -> BGR Dönüşümü
                frame_bgr = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
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
                        payload = f"MOUSE {dx} {dy}\n".encode('utf-8')
                        client_socket.sendall(payload)
                        time.sleep(random.uniform(0.0011, 0.0022))

                else:
                    target_detected_time = None
                    REACTION_DELAY = random.uniform(0.12, 0.18)
                    mouse_engine.last_dx = 0
                    mouse_engine.last_dy = 0

        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"[-] Hata oluştu: {e}")
        finally:
            client_socket.close()
            server_socket.close()

if __name__ == "__main__":
    main()
    
