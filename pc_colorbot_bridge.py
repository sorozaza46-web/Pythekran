import socket
import time
import math
import random
import cv2
import numpy as np
import win32api
from mss import mss

# ==========================================
# SİSTEM VE AĞ AYARLARI
# ==========================================
PORT = 9999                  # TCP Portu
FOV_SIZE = 130               # Odak alanı (Gereksiz uzak morlukları eler)
DEADZONE = 2                 # 2 piksel içi kilitlenme alanı (Sıfır titreme)

# ==========================================
# İNSANSI HAREKET VE PID PARAMETRELERİ
# ==========================================
KP = 0.16                    # Proportional (Orantısal Yaklaşma)
KD = 0.05                    # Derivative (Hedefe yaklaşırken Frenleme)
MAX_STEP = 7                 # Ani sıçrama üst limiti (Fırlamayı engeller)

VK_V = 0x56                  # 'V' Tuşu Kodu

# ==========================================
# HSV MOR RENK FİLTRESİ
# ==========================================
LOWER_PURPLE = np.array([140, 110, 120], dtype=np.uint8)
UPPER_PURPLE = np.array([160, 255, 255], dtype=np.uint8)

# ==========================================
# İNSANSI MOUSE MOTORU (HUMANIZER)
# ==========================================
class HumanizedMouseEngine:
    def __init__(self):
        self.prev_dx = 0
        self.prev_dy = 0

    def reset(self):
        self.prev_dx = 0
        self.prev_dy = 0

    def calculate_step(self, raw_dx, raw_dy):
        dist = math.hypot(raw_dx, raw_dy)
        
        if dist <= DEADZONE:
            self.reset()
            return 0, 0

        # PID Frenleme Hesabı
        p_x = raw_dx * KP
        p_y = raw_dy * KP
        
        d_x = (raw_dx - self.prev_dx) * KD
        d_y = (raw_dy - self.prev_dy) * KD

        calc_x = p_x + d_x
        calc_y = p_y + d_y

        # İnsansı Mikro Kavis ve Titreme (Gereksiz düz çizgileri engeller)
        if dist > 8:
            jitter_x = random.uniform(-0.35, 0.35)
            jitter_y = random.uniform(-0.35, 0.35)
            calc_x += jitter_x
            calc_y += jitter_y

        # Dinamik Hız Sınırlayıcı (Yavaşlama Bölgesi)
        current_max = MAX_STEP
        if dist < 12:
            current_max = 2
        elif dist < 25:
            current_max = 4

        move_x = int(np.clip(calc_x, -current_max, current_max))
        move_y = int(np.clip(calc_y, -current_max, current_max))

        # Sıfır olmasını engelleyen minimum adım kontrolü
        if move_x == 0 and raw_dx != 0: move_x = 1 if raw_dx > 0 else -1
        if move_y == 0 and raw_dy != 0: move_y = 1 if raw_dy > 0 else -1

        self.prev_dx = raw_dx
        self.prev_dy = raw_dy

        return move_x, move_y


def get_screen_roi(sct, roi_box):
    sct_img = sct.grab(roi_box)
    img = np.array(sct_img)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


def is_v_pressed():
    return (win32api.GetAsyncKeyState(VK_V) & 0x8000) != 0


def find_best_target(img, center_x, center_y):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)
    
    # Alt %35'lik kısmı (Silah, eldiven, zemin morlukları) kesin olarak maskele
    h_roi, w_roi = mask.shape
    mask[int(h_roi * 0.65):, :] = 0

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None

    closest_dist = float('inf')
    best_target = None

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 30 or area > 1800:
            continue
            
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = float(h) / float(w) if w > 0 else 0
        if aspect_ratio < 0.6:
            continue

        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            # Kafa hizasına kilitlenme offseti
            cy = int(M["m01"] / M["m00"]) - int(h * 0.32)
            
            dist = (cx - center_x) ** 2 + (cy - center_y) ** 2
            if dist < closest_dist:
                closest_dist = dist
                best_target = (cx, cy)

    if best_target:
        dx = best_target[0] - center_x
        dy = best_target[1] - center_y
        return dx, dy

    return None, None


def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server_socket.bind(('0.0.0.0', PORT))
    server_socket.listen(1)
    
    print(f"[+] TCP Sunucu {PORT} portunda dinleniyor...")
    print("[+] Telefonda IP ve Port girerek bağlanın.")
    
    conn, addr = server_socket.accept()
    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[+] Telefon bağlandı: {addr}")

    sct = mss()
    monitor = sct.monitors[1]
    
    screen_center_x = monitor["width"] // 2
    screen_center_y = monitor["height"] // 2
    
    roi_box = {
        "top": screen_center_y - (FOV_SIZE // 2) - 10,
        "left": screen_center_x - (FOV_SIZE // 2),
        "width": FOV_SIZE,
        "height": FOV_SIZE
    }
    
    roi_center_x = FOV_SIZE // 2
    roi_center_y = (FOV_SIZE // 2) - 10

    engine = HumanizedMouseEngine()

    try:
        while True:
            if is_v_pressed():
                frame = get_screen_roi(sct, roi_box)
                raw_dx, raw_dy = find_best_target(frame, roi_center_x, roi_center_y)
                
                if raw_dx is not None and raw_dy is not None:
                    move_x, move_y = engine.calculate_step(raw_dx, raw_dy)

                    if move_x != 0 or move_y != 0:
                        payload = f"MOUSE {move_x} {move_y}\n".encode('utf-8')
                        conn.sendall(payload)
                        # İnsansı mikro-gecikme (Her karede rastgele milisaniyelik değişim)
                        time.sleep(random.uniform(0.007, 0.009))
                    else:
                        time.sleep(0.004)
                else:
                    engine.reset()
                    time.sleep(0.004)
            else:
                engine.reset()
                time.sleep(0.01)

    except (ConnectionResetError, BrokenPipeError):
        print("[-] Telefon bağlantısı koptu.")
    except KeyboardInterrupt:
        print("\n[!] Kapatılıyor.")
    finally:
        conn.close()
        server_socket.close()

if __name__ == "__main__":
    main()
    
