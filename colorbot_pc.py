import socket
import struct
import time
import math
import random
import bettercam
import cv2
import numpy as np

# --- 1. İNSANSI HAREKET MOTORU (BÉZIER & GAUSSIAN NOISE) ---

def bezier_point(p0, p1, p2, t):
    """İkinci dereceden Bézier eğrisi ile insansı kavisli hareket hesabı"""
    return (1 - t)**2 * p0 + 2 * (1 - t) * t * p1 + t**2 * p2

def get_human_step(dx, dy, progress):
    """
    Hedef ile mevcut konum arasına insansı rastgele kavis ve titreme ekler.
    progress: 0.0 (başlangıç) - 1.0 (hedef) arası ilerleme
    """
    # Kavis için kontrol noktası (Control point) - İnsan elinin hafif sapması
    ctrl_x = dx * random.uniform(0.3, 0.7) + random.uniform(-5, 5)
    ctrl_y = dy * random.uniform(0.3, 0.7) + random.uniform(-5, 5)

    # Eğri üzerindeki anlık hedef
    target_x = bezier_point(0, ctrl_x, dx, progress)
    target_y = bezier_point(0, ctrl_y, dy, progress)

    # İnsan kaslarındaki mikro titreşim (Gaussian Noise)
    noise_x = random.gauss(0, 0.4)
    noise_y = random.gauss(0, 0.4)

    return target_x + noise_x, target_y + noise_y


# --- 2. ANA YAZILIM VE GİZLİLİK MİMARİSİ ---

def main():
    # Anticheat taramalarını yanıltmak için rastgele süreç başlığı ve port seçimi
    RANDOM_PORT = random.randint(20000, 45000)
    print(f"[*] Gizli Haberlesme Portu: {RANDOM_PORT}")
    print("[*] ADB Tünelini güncellemek için: adb forward udp:{0} udp:{0}".format(RANDOM_PORT))

    sock = socket.socket(socket.AF_INET, SOCK_DGRAM)
    target_addr = ('127.0.0.1', RANDOM_PORT)

    try:
        # DXGI Sürücüsü ile doğrudan GPU bellek aktarımı
        camera = bettercam.create(output_color="BGR")
    except Exception as e:
        return

    # Dinamik FOV: Sabit piksel boyutları yerine hafif değişken tarama alanı
    base_fov = 150
    screen_w, screen_h = 1920, 1080
    center_x = base_fov // 2
    center_y = base_fov // 2

    # OPTİMİZE EDİLMİŞ HASSAS MOR RENK PALETİ
    LOWER_PURPLE = np.array([142, 115, 135], dtype=np.uint8)
    UPPER_PURPLE = np.array([153, 255, 255], dtype=np.uint8)

    camera.start(region=((screen_w - base_fov)//2, (screen_h - base_fov)//2, 
                        (screen_w + base_fov)//2, (screen_h + base_fov)//2), 
                 target_fps=240)

    # Insansı Tepki Gecikmesi için Değişkenler
    target_detected_time = None
    REACTION_DELAY = random.uniform(0.11, 0.16) # 110ms - 160ms insan tepki süresi

    try:
        while True:
            frame = camera.get_latest_frame()
            if frame is None:
                continue

            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            mask = cv2.inRange(hsv, LOWER_PURPLE, UPPER_PURPLE)

            # Gürültü Temizleme
            kernel = np.ones((3, 3), np.uint8)
            mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

            M = cv2.moments(mask, binaryImage=True)
            if M["m00"] > 60:
                # Hedef ilk kez görüldüyse insansı tepki süresi bekle
                if target_detected_time is None:
                    target_detected_time = time.time()

                # Tepki süresi dolmadıysa ateş/hareket etme (Robotik refleks engelleme)
                if time.time() - target_detected_time < REACTION_DELAY:
                    continue

                cx = int(M["m10"] / M["m00"])
                cy = int(M["m01"] / M["m00"])

                raw_dx = cx - center_x
                raw_dy = cy - center_y

                # İnsansı Eğrisel Hareket Adımı (Progress %25 civarı adım katsayısı)
                step_x, step_y = get_human_step(raw_dx, raw_dy, progress=0.28)

                dx = max(-127, min(127, int(step_x)))
                dy = max(-127, min(127, int(step_y)))

                if dx != 0 or dy != 0:
                    sock.sendto(struct.pack('bb', dx, dy), target_addr)
                    # İnsan elindeki polling rate dalgalanması (1000Hz - 500Hz arası mikro gecikme)
                    time.sleep(random.uniform(0.001, 0.0025))

            else:
                # Hedef görüş alanından çıktığında tepki süresini ve kavisleri sıfırla
                target_detected_time = None
                REACTION_DELAY = random.uniform(0.11, 0.16)

    except KeyboardInterrupt:
        pass
    finally:
        camera.stop()
        sock.close()

if __name__ == "__main__":
    main()
    
