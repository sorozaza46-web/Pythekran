import socket
import time
import math
import cv2
import numpy as np
import win32api
from mss import mss

# ==========================================
# GÜNCELLENMİŞ VE YUMUŞATILMIŞ AYARLAR
# ==========================================
PORT = 9999                  # TCP Portu
FOV_SIZE = 160               # FOV küçültüldü: Yanlış hedeflere fırlamayı doğrudan engeller
DEADZONE = 2                 # 2 piksel yakınlıktaysa hareketi kes (titremeyi engeller)

# Hassasiyet Ayarları (Oyundaki sens yüksekse KP'yi düşürün, örn: 0.12)
KP = 0.18                    # Hassasiyet Çarpanı (Daha pürüzsüz takip)
MAX_STEP = 6                 # Tek seferde atılacak maksimum adım (Fırlamayı kesin olarak engeller)

VK_V = 0x56                  # 'V' Tuşu Kodu

# ==========================================
# RENK ARALIĞI (Daha Saf Mor)
# ==========================================
LOWER_PURPLE = np.array([140, 110, 120])
UPPER_PURPLE = np.array([160, 255, 255])

# ==========================================
# FONKSİYONLAR
# ==========================================

def get_screen_roi(sct, roi_box):
    """Ekranın merkezindeki ROI alanını yakalar."""
    sct_img = sct.grab(roi_box)
    img = np.array(sct_img)
    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

def is_v_pressed():
    """V tuşunun basılı olup olmadığını kontrol eder."""
    return (win32api.GetAsyncKeyState(VK_V) & 0x8000) != 0

def find_best_target(img, center_x, center_y):
    """
    Gelişmiş Görüntü İşleme:
    - Arka plan parazitlerini temizler.
    - Merkeze en yakın mor konturu tespit eder.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)
    
    # Parazit temizleme
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
        
        # Çok küçük (parazit) ve çok büyük alanları ele
        if area < 30 or area > 2000:
            continue
            
        x, y, w, h = cv2.boundingRect(contour)
        
        # En-Boy Oranı Filtresi (Çok yayvan şekilleri ele)
        aspect_ratio = float(h) / float(w) if w > 0 else 0
        if aspect_ratio < 0.6:
            continue

        M = cv2.moments(contour)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            # Hedefin biraz daha üstüne (kafa seviyesine) odaklanmak için cy ayarlaması
            cy = int(M["m01"] / M["m00"]) - int(h * 0.15)
            
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
    print("[+] Telefonda IP ve Port girerek bağlanın.")
    
    conn, addr = server_socket.accept()
    print(f"[+] Telefon bağlandı: {addr}")

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

    # Yumuşatma değişkenleri
    smoothed_dx = 0.0
    smoothed_dy = 0.0

    try:
        while True:
            if is_v_pressed():
                frame = get_screen_roi(sct, roi_box)
                raw_dx, raw_dy = find_best_target(frame, roi_center_x, roi_center_y)
                
                if raw_dx is not None and raw_dy is not None:
                    # Exponential Moving Average (İvme Yumuşatma - Ani fırlamaları keser)
                    smoothed_dx = (smoothed_dx * 0.4) + (raw_dx * 0.6)
                    smoothed_dy = (smoothed_dy * 0.4) + (raw_dy * 0.6)

                    # Deadzone Kontrolü
                    calc_dx = smoothed_dx if abs(smoothed_dx) > DEADZONE else 0
                    calc_dy = smoothed_dy if abs(smoothed_dy) > DEADZONE else 0
                        
                    if calc_dx != 0 or calc_dy != 0:
                        # Orantısal Adım Hesabı
                        move_x = int(calc_dx * KP)
                        move_y = int(calc_dy * KP)

                        # En küçük hareket garantisi
                        if move_x == 0 and calc_dx != 0: move_x = 1 if calc_dx > 0 else -1
                        if move_y == 0 and calc_dy != 0: move_y = 1 if calc_dy > 0 else -1

                        # Sert Hız Limiti (Sapan gibi fırlamayı engeller)
                        move_x = clamp(move_x, -MAX_STEP, MAX_STEP)
                        move_y = clamp(move_y, -MAX_STEP, MAX_STEP)

                        # Ağ Paketini Yolla
                        payload = f"MOUSE {move_x} {move_y}\n"
                        conn.sendall(payload.encode('utf-8'))

                        time.sleep(0.008)
                else:
                    smoothed_dx, smoothed_dy = 0.0, 0.0
                    time.sleep(0.005)
            else:
                smoothed_dx, smoothed_dy = 0.0, 0.0
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
    
