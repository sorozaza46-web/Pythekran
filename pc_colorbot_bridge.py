import socket
import time
import math
import random
import cv2
import numpy as np
import win32api
import dxcam  # GPU Direct Frame Capture (DXGI)

# ==========================================
# SİSTEM VE AĞ AYARLARI
# ==========================================
PORT = 9999                  # TCP Portu
FOV_SIZE = 140               # Odak alanı genişliği
DEADZONE = 1                 # Hassasiyet artırıldı (1 Piksel)

# ==========================================
# İNSANSI GELİŞMİŞ AYARLAR
# ==========================================
BASE_KP = 0.13               # Temel takip hızı
SMOOTH_FACTOR = 0.65         # Yumuşatma çarpanı
MAX_STEP = 6.0               # Maksimum adım sınırı

# ==========================================
# TUŞ KODLARI
# ==========================================
VK_V = 0x56                  # 'V' Tuşu (Ana Aç / Kapat Anahtarı)
VK_LBUTTON = 0x01            # Sol Fare Tıkı (Anlık Basılı Tutma Tetiği)

# ==========================================
# MOR RENK ARALIĞI
# ==========================================
LOWER_PURPLE = np.array([135, 75, 90], dtype=np.uint8)  # Uzaktaki soluk pikseller için tolerans genişletildi
UPPER_PURPLE = np.array([165, 255, 255], dtype=np.uint8)

# Global Durum Değişkenleri
system_enabled = False
last_v_state = False

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

        # Kas İrkilmesi / Algılama Gecikmesi
        if self.curr_vx == 0 and self.curr_vy == 0:
            if self.reaction_delay_counter < random.randint(1, 2):
                self.reaction_delay_counter += 1
                return 0, 0

        # Uzaktaki Hedefler İçin Dinamik Hız Tespiti
        dyn_kp = BASE_KP * random.uniform(0.96, 1.04)
        
        if dist > 40:
            kp = dyn_kp * 1.35   # Uzak hedeflerde hızlı yanıt
            smooth = SMOOTH_FACTOR * 0.65
        elif dist > 15:
            kp = dyn_kp
            smooth = SMOOTH_FACTOR
        else:
            kp = dyn_kp * 0.60
            smooth = SMOOTH_FACTOR * 1.25

        target_vx = raw_dx * kp
        target_vy = raw_dy * kp

        # Asimetrik Kavis & Bezier Eğrisi
        curve_factor_x = random.uniform(0.89, 1.11)
        curve_factor_y = random.uniform(0.95, 1.05)

        self.curr_vx = (self.curr_vx * smooth) + (target_vx * (1.0 - smooth)) * curve_factor_x
        self.curr_vy = (self.curr_vy * smooth) + (target_vy * (1.0 - smooth)) * curve_factor_y

        # Overshoot (Taşma ve Düzeltme)
        if dist > 25 and random.random() < 0.15:
            self.curr_vx *= 1.07
            self.curr_vy *= 1.07

        # Biyometrik Mikro Titreme
        if dist > 4 and random.random() < 0.22:
            self.curr_vx += random.uniform(-0.30, 0.30)
            self.curr_vy += random.uniform(-0.30, 0.30)

        # Dinamik Hız Sınırlama
        limit = MAX_STEP
        if dist < 5:
            limit = 1.2
        elif dist < 12:
            limit = 2.2

        scaled_vx = np.clip(self.curr_vx, -limit, limit)
        scaled_vy = np.clip(self.curr_vy, -limit, limit)

        # Sub-pixel Akümülatörü
        total_x = scaled_vx + self.remainder_x
        total_y = scaled_vy + self.remainder_y

        move_x = int(math.trunc(total_x))
        move_y = int(math.trunc(total_y))

        self.remainder_x = total_x - move_x
        self.remainder_y = total_y - move_y

        # Uzaktaki 1-2 piksellik hassas kaymaları atlamamak için min adımlama
        if move_x == 0 and raw_dx != 0 and abs(raw_dx) > DEADZONE:
            move_x = 1 if raw_dx > 0 else -1
        if move_y == 0 and raw_dy != 0 and abs(raw_dy) > DEADZONE:
            move_y = 1 if raw_dy > 0 else -1

        return move_x, move_y


def check_toggle_keys():
    """
    'V' Tuşu: Genel Sistem Durumu (Aç / Kapat Toggle)
    Sol Tık: Parmağın sol tıka basılı tutulduğu anlarda takip yapar, 
             bırakıldığı salisede takibi ve odaklanmayı durdurur.
    """
    global system_enabled, last_v_state
    
    current_v_state = (win32api.GetAsyncKeyState(VK_V) & 0x8000) != 0
    
    if current_v_state and not last_v_state:
        system_enabled = not system_enabled
        status_str = "AKTİF" if system_enabled else "PASİF"
        print(f"[!] Sistem Durumu: {status_str}")
        
    last_v_state = current_v_state

    # Sol Tıkın Anlık Basılma Durumu
    is_lbutton_down = (win32api.GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0

    return system_enabled and is_lbutton_down


def find_best_target(img, center_x, center_y):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)
    
    h_roi, w_roi = mask.shape
    mask[int(h_roi * 0.68):, :] = 0  

    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None

    closest_dist = float('inf')
    best_target = None

    for contour in contours:
        area = cv2.contourArea(contour)
        
        # UZAK HEDEF DÜZELTMESİ:
        # Minimum alan threshold'u 6'ya düşürüldü. Uzaktaki pikseller elenmiyor.
        if area < 6 or area > 3000:
            continue
            
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = float(h) / float(w) if w > 0 else 0
        if aspect_ratio < 0.35:
            continue

        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            
            # Mesafeye/Boyuta Göre Dinamik Kafa Hizalaması
            if h > 25:
                head_offset = int(h * 0.36)
            elif h > 10:
                head_offset = int(h * 0.30)
            else:
                head_offset = int(h * 0.22)
                
            head_offset += int(np.random.normal(0, 0.7))  
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
    camera = dxcam.create(output_idx=0, output_color="BGR")
    
    screen_width, screen_height = camera.width, camera.height
    screen_center_x = screen_width // 2
    screen_center_y = screen_height // 2

    left = screen_center_x - (FOV_SIZE // 2)
    top = screen_center_y - (FOV_SIZE // 2) - 10
    right = left + FOV_SIZE
    bottom = top + FOV_SIZE

    region = (left, top, right, bottom)
    camera.start(region=region, target_fps=144, video_mode=True)

    roi_center_x = FOV_SIZE // 2
    roi_center_y = (FOV_SIZE // 2) - 10

    engine = ProHumanMouseEngine()

    print("[+] GPU DXGI Capture Engine Başlatıldı.")
    print("[+] 'V' Tuşu: Ana Aç / Kapat")
    print("[+] Sol Tık: Basılı Tutulduğunda Takip Et / Bırakıldığında Anında Dur")

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
                should_aim = check_toggle_keys()

                if should_aim:
                    # Sol tık basılı olduğu sürece odaklanır ve kilitlenir
                    frame = camera.get_latest_frame()
                    
                    if frame is not None:
                        raw_dx, raw_dy = find_best_target(frame, roi_center_x, roi_center_y)
                        
                        if raw_dx is not None and raw_dy is not None:
                            move_x, move_y = engine.calculate_step(raw_dx, raw_dy)

                            if move_x != 0 or move_y != 0:
                                payload = f"MOUSE {move_x} {move_y}\n".encode('utf-8')
                                conn.sendall(payload)
                                
                                base_sleep = random.uniform(0.005, 0.009)
                                if random.random() < 0.08:
                                    base_sleep += random.uniform(0.003, 0.006)
                                    
                                time.sleep(base_sleep)
                            else:
                                time.sleep(0.003)
                        else:
                            time.sleep(0.003)
                    else:
                        time.sleep(0.001)
                else:
                    # Sol tık bırakıldığı AN hareketi ve motor ivmesini durdurur
                    engine.reset()
                    time.sleep(0.005)

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
            camera.stop()
            break

if __name__ == "__main__":
    main()
            
