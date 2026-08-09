import socket
import time
import math
import random
import cv2
import numpy as np
import win32api
from mss import mss

# ==========================================
# GELIŞMIŞ AYARLAR (ADVANCED CONFIG)
# ==========================================
PORT = 9999                  # TCP Portu
FOV_SIZE = 300               # Tarama alanı (300x300 piksel)
DEADZONE = 2                 # Hedeften kaç piksel kalana kadar hareket edilsin

VK_V = 0x56                  # 'V' Tuşu Kodu

# Mor / Magenta Renk Aralığı (HSV)
LOWER_PURPLE = np.array([135, 110, 110])
UPPER_PURPLE = np.array([165, 255, 255])

# Hedef Ofseti (Kafaya kilitlenmek istenirse Y değerini eksi yapabilirsiniz, örn: -6)
TARGET_OFFSET_Y = 0

# ==========================================
# İNSANSI HAREKET MOTORU (HUMAN MOTION ENGINE)
# ==========================================

class HumanMotionEngine:
    def __init__(self):
        self.is_overshooting = False
        self.overshoot_dx = 0
        self.overshoot_dy = 0

    def calculate_step(self, dx, dy, dist):
        """Fitts Yasası, Gauss Titremesi ve Bilek Eğriliği ile adım hesabı yapar."""
        
        # 1. Dynamic Smoothing (Fitts Yasası İlhama Dayalı Yavaşlama)
        if dist > 120:
            smooth = random.uniform(1.8, 2.2)  # Hızlı atış (Flick)
        elif dist > 40:
            smooth = random.uniform(2.3, 3.2)  # Yaklaşma
        else:
            smooth = random.uniform(3.3, 4.5)  # Hassas odaklanma

        # 2. İvmeli (Ease-Out) Adım Hesabı
        step_x = dx / smooth
        step_y = dy / smooth

        # 3. Bilek Dönme Kavis Sapması (Düz çizgi yerine doğal eğri çizer)
        if dist > 15:
            # Vektöre dik açı yönünde küçük bir sapma ekler
            curve_factor = random.uniform(-0.12, 0.12)
            step_x += -dy * curve_factor / dist
            step_y +=  dx * curve_factor / dist

        # 4. Fizyolojik El Titremesi (Gaussian Micro-Jitter)
        jitter_x = random.gauss(0, 0.35)
        jitter_y = random.gauss(0, 0.35)

        final_x = step_x + jitter_x
        final_y = step_y + jitter_y

        # Tam sayıya yuvarlama
        int_x = int(round(final_x))
        int_y = int(round(final_y))

        # Minimum 1 piksel hareket koruması
        if int_x == 0 and dx != 0:
            int_x = 1 if dx > 0 else -1
        if int_y == 0 and dy != 0:
            int_y = 1 if dy > 0 else -1

        return int_x, int_y

    def check_overshoot(self, dx, dy, dist):
        """Hızlı hareketlerde %12 ihtimalle hedefi hafifçe aşma simülasyonu."""
        if not self.is_overshooting and dist > 60 and random.random() < 0.12:
            self.is_overshooting = True
            # Target'ı 2-5 piksel aşacak yönde ek kuvvet oluştur
            self.overshoot_dx = int((dx / dist) * random.randint(2, 5))
            self.overshoot_dy = int((dy / dist) * random.randint(2, 5))
            return self.overshoot_dx, self.overshoot_dy
        
        if self.is_overshooting:
            # Aşılan mesafeyi geri düzelt
            corr_x = -self.overshoot_dx
            corr_y = -self.overshoot_dy
            self.is_overshooting = False
            return corr_x, corr_y

        return 0, 0

# ==========================================
# ANA SİSTEM
# ==========================================

def get_screen_roi(sct, roi_box):
    sct_img = sct.grab(roi_box)
    img = np.array(sct_img)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

def is_v_pressed():
    return (win32api.GetAsyncKeyState(VK_V) & 0x8000) != 0

def find_target_offset(img, center_x, center_y):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)
    
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None

    closest_dist = float('inf')
    best_target = None

    for contour in contours:
        if cv2.contourArea(contour) < 8:
            continue
            
        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"]) + TARGET_OFFSET_Y
            
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
    motion_engine = HumanMotionEngine()
    
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server_socket.bind(('0.0.0.0', PORT))
    server_socket.listen(1)
    
    print(f"[+] TCP Sunucu {PORT} portunda dinleniyor...")
    print("[+] Telefonda IP/Port girip bağlanın.")
    
    conn, addr = server_socket.accept()
    print(f"[+] Telefon bağlandı: {addr}")
    print("[+] 'V' tuşuna basılı tutulduğunda gelişmiş insansı mod aktifleşir.")

    sct = mss()
    monitor = sct.monitors[1]
    
    screen_center_x = monitor["width"] // 2
    screen_center_y = monitor["height"] // 2
    
    roi_box = {
        "top": screen_center_y - (FOV_SIZE // 2),
        "left": screen_center_x - (FOV_SIZE // 2),
        "width": FOV_SIZE,
        "height": FOV_SIZE
    }
    
    roi_center_x = FOV_SIZE // 2
    roi_center_y = FOV_SIZE // 2

    was_v_pressed_last_frame = False

    try:
        while True:
            v_pressed = is_v_pressed()

            # V tuşuna ilk basıldığı an insan tepki süresini (Reaction Lag) simüle et
            if v_pressed and not was_v_pressed_last_frame:
                time.sleep(random.uniform(0.012, 0.028)) # 12-28 ms mikro tepki gecikmesi

            was_v_pressed_last_frame = v_pressed

            if v_pressed:
                frame = get_screen_roi(sct, roi_box)
                raw_dx, raw_dy = find_target_offset(frame, roi_center_x, roi_center_y)
                
                if raw_dx is not None and raw_dy is not None:
                    dist = math.hypot(raw_dx, raw_dy)
                    
                    # Deadzone kontrolü
                    if abs(raw_dx) <= DEADZONE: raw_dx = 0
                    if abs(raw_dy) <= DEADZONE: raw_dy = 0
                        
                    if raw_dx != 0 or raw_dy != 0:
                        # 1. Overshoot (Aşma) Kontrolü
                        ov_x, ov_y = motion_engine.check_overshoot(raw_dx, raw_dy, dist)
                        target_dx = raw_dx + ov_x
                        target_dy = raw_dy + ov_y

                        # 2. İnsansı Adım Hesabı (Fitts + Jitter + Curve)
                        move_x, move_y = motion_engine.calculate_step(target_dx, target_dy, dist)

                        # 3. Paket Gönderimi (TCP üzerinden Telefona)
                        payload = f"MOUSE {move_x} {move_y}\n"
                        conn.sendall(payload.encode('utf-8'))

            # İnsansı döngü zamanlaması dalgalanması
            time.sleep(random.uniform(0.0015, 0.0035))

    except (ConnectionResetError, BrokenPipeError):
        print("[-] Telefon bağlantısı koptu.")
    except KeyboardInterrupt:
        print("\n[!] Kapatılıyor.")
    finally:
        conn.close()
        server_socket.close()

if __name__ == "__main__":
    main()
