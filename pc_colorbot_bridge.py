import socket
import time
import math
import cv2
import numpy as np
import win32api
from mss import mss

# ==========================================
# AYARLAR (CONFIG)
# ==========================================
PORT = 9999                  # TCP Portu
FOV_SIZE = 300               # Tarama alanı (300x300 piksel)
DEADZONE = 3                 # Hedeften 3 piksel yakınlıktayken hareketi durdur (titremeyi önler)
MAX_STEP = 12                # Tek seferde gönderilebilecek MAKSİMUM piksel hareketi (Fırlamayı önler)
KP = 0.35                    # Hassasiyet Çarpanı (Düşük = Daha yavaş/stabil, Yüksek = Daha hızlı)

VK_V = 0x56                  # 'V' Tuşu Kodu

# Mor / Pembe Renk Aralığı (HSV)
LOWER_PURPLE = np.array([120, 50, 50])
UPPER_PURPLE = np.array([170, 255, 255])

# ==========================================
# FONSİYONLAR
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
    
    # Parazit temizleme
    kernel = np.ones((3, 3), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contours:
        return None, None

    closest_dist = float('inf')
    best_target = None

    for contour in contours:
        if cv2.contourArea(contour) < 10: # Çok küçük noktaları ele
            continue
            
        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
            
            dist = (cx - center_x) ** 2 + (cy - center_y) ** 2
            if dist < closest_dist:
                closest_dist = dist
                best_target = (cx, cy)

    if best_target:
        dx = best_target[0] - center_x
        dy = best_target[1] - center_y
        return dx, dy

    return None, None

def clamp(val, min_val, max_val):
    return max(min_val, min(max_val, val))

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    server_socket.bind(('0.0.0.0', PORT))
    server_socket.listen(1)
    
    print(f"[+] TCP Sunucu {PORT} portunda dinleniyor...")
    print("[+] Telefonda IP/Port girip bağlanın.")
    
    conn, addr = server_socket.accept()
    print(f"[+] Telefon bağlandı: {addr}")

    sct = mss()
    monitor = sct.monitors[1] # 1. Monitör
    
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

    try:
        while True:
            if is_v_pressed():
                frame = get_screen_roi(sct, roi_box)
                raw_dx, raw_dy = find_target_offset(frame, roi_center_x, roi_center_y)
                
                if raw_dx is not None and raw_dy is not None:
                    # Deadzone kontrolü (Hedefe ulaşıldıysa dur)
                    if abs(raw_dx) <= DEADZONE: raw_dx = 0
                    if abs(raw_dy) <= DEADZONE: raw_dy = 0
                        
                    if raw_dx != 0 or raw_dy != 0:
                        # Orantısal Adım Hesabı
                        move_x = int(raw_dx * KP)
                        move_y = int(raw_dy * KP)

                        # Minimum 1 piksel hareket koruması
                        if move_x == 0 and raw_dx != 0: move_x = 1 if raw_dx > 0 else -1
                        if move_y == 0 and raw_dy != 0: move_y = 1 if raw_dy > 0 else -1

                        # Adım Sınırlaması (Aşırı fırlamayı engeller)
                        move_x = clamp(move_x, -MAX_STEP, MAX_STEP)
                        move_y = clamp(move_y, -MAX_STEP, MAX_STEP)

                        # Paket Gönderimi
                        payload = f"MOUSE {move_x} {move_y}\n"
                        conn.sendall(payload.encode('utf-8'))

                        # GECİKME BEKLEMESİ (Bluetooth ve Ekranın Güncellenmesi İçin Kritik Süre)
                        time.sleep(0.015) # 15 ms
                else:
                    time.sleep(0.005)
            else:
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
