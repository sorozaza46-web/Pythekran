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
FOV_SIZE = 140               # Odak alanı genişliği
DEADZONE = 2                 # Kilitlenme toleransı (Piksel)

# ==========================================
# YUMUŞATILMIŞ HAREKET AYARLARI
# ==========================================
KP = 0.12                    # Düşük katsayı = Ekstra yumuşak takip
SMOOTH_FACTOR = 0.55         # İvme yumuşatma çarpanı (Artırıldı = Daha akıcı/insansı)
MAX_STEP = 4                 # Tek seferde atılabilecek MAKSİMUM adım (Ani sıçramayı önler)

VK_V = 0x56                  # 'V' Tuşu Kodu

# ==========================================
# MOR RENK ARALIĞI
# ==========================================
LOWER_PURPLE = np.array([135, 80, 100], dtype=np.uint8)
UPPER_PURPLE = np.array([165, 255, 255], dtype=np.uint8)

# ==========================================
# YUMUŞATILMIŞ FARE MOTORU
# ==========================================
class SmoothMouseEngine:
    def __init__(self):
        self.curr_vx = 0.0
        self.curr_vy = 0.0

    def reset(self):
        self.curr_vx = 0.0
        self.curr_vy = 0.0

    def calculate_step(self, raw_dx, raw_dy):
        dist = math.hypot(raw_dx, raw_dy)
        
        if dist <= DEADZONE:
            self.reset()
            return 0, 0

        target_vx = raw_dx * KP
        target_vy = raw_dy * KP

        # Exponential Moving Average (İnsansı yumuşak ivme)
        self.curr_vx = (self.curr_vx * SMOOTH_FACTOR) + (target_vx * (1.0 - SMOOTH_FACTOR))
        self.curr_vy = (self.curr_vy * SMOOTH_FACTOR) + (target_vy * (1.0 - SMOOTH_FACTOR))

        # Frenleme bölgesi
        limit = MAX_STEP
        if dist < 10:
            limit = 2.0
        elif dist < 20:
            limit = 3.0

        move_x = int(np.clip(self.curr_vx, -limit, limit))
        move_y = int(np.clip(self.curr_vy, -limit, limit))

        if move_x == 0 and raw_dx != 0: move_x = 1 if raw_dx > 0 else -1
        if move_y == 0 and raw_dy != 0: move_y = 1 if raw_dy > 0 else -1

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
    
    h_roi, w_roi = mask.shape
    mask[int(h_roi * 0.70):, :] = 0

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    mask = cv2.dilate(mask, kernel, iterations=1)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None

    closest_dist = float('inf')
    best_target = None

    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 20 or area > 2200:
            continue
            
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = float(h) / float(w) if w > 0 else 0
        if aspect_ratio < 0.5:
            continue

        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            head_offset = int(h * 0.25) if h > 20 else int(h * 0.15)
            cy = int(M["m01"] / M["m00"]) - head_offset
            
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

    engine = SmoothMouseEngine()

    # ÇÖKMEYİ ÖNLEYEN SÜREKLİ DİNLEME DÖNGÜSÜ
    while True:
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            server_socket.bind(('0.0.0.0', PORT))
            server_socket.listen(1)
            
            print(f"\n[+] Sunucu hazır. {PORT} portunda bağlantı bekleniyor...")
            conn, addr = server_socket.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[+] Bağlantı sağlandı: {addr}")

            while True:
                if is_v_pressed():
                    frame = get_screen_roi(sct, roi_box)
                    raw_dx, raw_dy = find_best_target(frame, roi_center_x, roi_center_y)
                    
                    if raw_dx is not None and raw_dy is not None:
                        move_x, move_y = engine.calculate_step(raw_dx, raw_dy)

                        if move_x != 0 or move_y != 0:
                            payload = f"MOUSE {move_x} {move_y}\n".encode('utf-8')
                            conn.sendall(payload)
                            time.sleep(random.uniform(0.008, 0.010))
                        else:
                            time.sleep(0.004)
                    else:
                        engine.reset()
                        time.sleep(0.004)
                else:
                    engine.reset()
                    time.sleep(0.01)

        except (ConnectionResetError, BrokenPipeError, socket.error) as e:
            print(f"[-] Bağlantı koptu ({e}). Yeniden bağlanması bekleniyor...")
            engine.reset()
            try:
                conn.close()
                server_socket.close()
            except:
                pass
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n[!] Kullanıcı tarafından kapatıldı.")
            break

if __name__ == "__main__":
    main()
    
