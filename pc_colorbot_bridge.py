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
FOV_SIZE = 130               # Odak alanı genişliği
DEADZONE = 2                 # Kilitlenme toleransı (Piksel)

# ==========================================
# İNSANSI GELİŞMİŞ AYARLAR
# ==========================================
BASE_KP = 0.12               # Temel takip hızı (Daha doğal geçiş için hafif düşürüldü)
SMOOTH_FACTOR = 0.68         # Yumuşatma çarpanı
MAX_STEP = 5.5               # Ani sıçramaları önleyen maksimum adım sınırı

VK_V = 0x56                  # 'V' Tuşu Kodu

# ==========================================
# MOR RENK ARALIĞI
# ==========================================
LOWER_PURPLE = np.array([135, 80, 100], dtype=np.uint8)
UPPER_PURPLE = np.array([165, 255, 255], dtype=np.uint8)

# ==========================================
# PRO HUMAN MOUSE ENGINE (ADVANCED BIOMECHANICS)
# ==========================================
class ProHumanMouseEngine:
    def __init__(self):
        self.curr_vx = 0.0
        self.curr_vy = 0.0
        self.remainder_x = 0.0  
        self.remainder_y = 0.0
        self.reaction_delay_counter = 0

    def reset(self):
        self.curr_vx = 0.0
        self.curr_vy = 0.0
        self.remainder_x = 0.0
        self.remainder_y = 0.0
        self.reaction_delay_counter = 0

    def calculate_step(self, raw_dx, raw_dy):
        dist = math.hypot(raw_dx, raw_dy)
        
        if dist <= DEADZONE:
            self.reset()
            return 0, 0

        # 1. İnsansı İnsan Reaksiyon Gecikmesi (Kas İrkilmesi / Muscle Latency)
        # Hedef ilk tespit edildiğinde 1-2 döngü çok hafif tepkisizlik simüle edilir
        if self.curr_vx == 0 and self.curr_vy == 0:
            if self.reaction_delay_counter < random.randint(1, 2):
                self.reaction_delay_counter += 1
                return 0, 0

        # 2. Dinamik Fitts Yasası & S-Curve Hız Profili
        if dist > 45:
            kp = BASE_KP * 1.20
            smooth = SMOOTH_FACTOR * 0.70
        elif dist > 18:
            kp = BASE_KP
            smooth = SMOOTH_FACTOR
        else:
            kp = BASE_KP * 0.55
            smooth = SMOOTH_FACTOR * 1.30  # Yakın mesafe mikro düzeltme yumuşaklığı

        target_vx = raw_dx * kp
        target_vy = raw_dy * kp

        # 3. Asimetrik Eksensel Kavis & Bezier Eğrisi Simülasyonu
        # İnsan eli X (yatay) ve Y (dikey) ekseninde aynı ivmeyle hareket edemez.
        curve_factor_x = random.uniform(0.88, 1.12)
        curve_factor_y = random.uniform(0.94, 1.06)

        self.curr_vx = (self.curr_vx * smooth) + (target_vx * (1.0 - smooth)) * curve_factor_x
        self.curr_vy = (self.curr_vy * smooth) + (target_vy * (1.0 - smooth)) * curve_factor_y

        # 4. Overshoot / Hedefi Geçip Düzeltme (Hızlı Sıçramalarda)
        # Mesafe yüksekse %15 ihtimalle hedef biraz aşılır ve geri toplanır.
        if dist > 30 and random.random() < 0.15:
            self.curr_vx *= 1.08
            self.curr_vy *= 1.08

        # 5. Biyometrik Mikro Titreme (Physiological Jitter)
        if dist > 5 and random.random() < 0.25:
            jitter_x = random.uniform(-0.35, 0.35)
            jitter_y = random.uniform(-0.35, 0.35)
            self.curr_vx += jitter_x
            self.curr_vy += jitter_y

        # 6. Dinamik Hız Sınırlama (Frenleme)
        limit = MAX_STEP
        if dist < 6:
            limit = 1.3
        elif dist < 15:
            limit = 2.4

        scaled_vx = np.clip(self.curr_vx, -limit, limit)
        scaled_vy = np.clip(self.curr_vy, -limit, limit)

        # 7. Sub-pixel Akümülatörü (Ondalık Hassasiyet Belleği)
        total_x = scaled_vx + self.remainder_x
        total_y = scaled_vy + self.remainder_y

        move_x = int(math.trunc(total_x))
        move_y = int(math.trunc(total_y))

        self.remainder_x = total_x - move_x
        self.remainder_y = total_y - move_y

        # Minimum Adım Düzeltmesi (Ölü noktaları aşma)
        if move_x == 0 and raw_dx != 0 and abs(raw_dx) > DEADZONE:
            move_x = 1 if raw_dx > 0 else -1
        if move_y == 0 and raw_dy != 0 and abs(raw_dy) > DEADZONE:
            move_y = 1 if raw_dy > 0 else -1

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
    # Alt kısmı daha agresif keserek odağı kafa ve boyun bölgesine topluyoruz
    mask[int(h_roi * 0.62):, :] = 0  

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
            
            # --- YUKARI HİZALAMA VE İNSANSI RASTGELELİK ---
            # h * 0.36 oranı ile hedef tam kafa hizasına taşındı.
            head_offset = int(h * 0.36) if h > 20 else int(h * 0.24)
            
            # Sabit nokta kilitlenmesini bozmak için Gauss dağılımlı mikro sapma
            head_offset += int(np.random.normal(0, 0.8))  
            
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

    engine = ProHumanMouseEngine()

    while True:
        try:
            server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            server_socket.bind(('0.0.0.0', PORT))
            server_socket.listen(1)
            
            print(f"\n[+] Sunucu aktif. Port: {PORT}")
            conn, addr = server_socket.accept()
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            print(f"[+] Bağlandı: {addr}")

            while True:
                if is_v_pressed():
                    frame = get_screen_roi(sct, roi_box)
                    raw_dx, raw_dy = find_best_target(frame, roi_center_x, roi_center_y)
                    
                    if raw_dx is not None and raw_dy is not None:
                        move_x, move_y = engine.calculate_step(raw_dx, raw_dy)

                        if move_x != 0 or move_y != 0:
                            payload = f"MOUSE {move_x} {move_y}\n".encode('utf-8')
                            conn.sendall(payload)
                            
                            # İnsansı Zamanlama Dalgalanması (Variable Polling Frequency)
                            # Sabit gecikmeler yerine insan el kaslarının tutarsızlığı simüle edilir.
                            base_sleep = random.uniform(0.005, 0.010)
                            if random.random() < 0.08:  # %8 ihtimalle anlık insansı duraklama (micro-pause)
                                base_sleep += random.uniform(0.003, 0.007)
                                
                            time.sleep(base_sleep)
                        else:
                            time.sleep(0.003)
                    else:
                        engine.reset()
                        time.sleep(0.003)
                else:
                    engine.reset()
                    time.sleep(0.01)

        except (ConnectionResetError, BrokenPipeError, socket.error) as e:
            print(f"[-] Bağlantı kesildi ({e}). Yeniden bekleniyor...")
            engine.reset()
            try:
                conn.close()
                server_socket.close()
            except:
                pass
            time.sleep(1)
            
        except KeyboardInterrupt:
            print("\n[!] Program durduruldu.")
            break

if __name__ == "__main__":
    main()
    
