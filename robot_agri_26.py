import sys
sys.path.append('/home/kit12/adeept_picar-pro/Server')

import socket
import struct
import cv2
import numpy as np
import time
import threading
import requests
import Move as move
from RPIservo import ServoCtrl
from gpiozero import TonalBuzzer
import Switch as sw

PC_IP = '10.52.73.105'
PORT  = 9999

buzzer = TonalBuzzer(18)
move.setup()
sc = ServoCtrl()
sw.switchSetup()

CX_IMAGE = 320
SEUIL_X  = 30
S1_MIN, S1_MAX = 40, 180
KP_X = 0.08

S1_TRAVAIL = 135
S2_TRAVAIL = 125

HSV_BAS  = np.array([0, 100, 60])
HSV_HAUT = np.array([10, 255, 255])
HSV_BAS2 = np.array([170, 100, 60])
HSV_HAUT2 = np.array([180, 255, 255])

desherbage_actif = False
detection_flag   = False
detection_data   = None
detection_lock   = threading.Lock()

t_fin_desherbage = 0
COOLDOWN_SEC = 15.0  # 15s anti fausse re-detection apres reprise

buf = b''
socket_lock = threading.Lock()

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((PC_IP, PORT))
print("Connecte au PC")

camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
time.sleep(1)
print("Live en cours...")


def thread_camera():
    global buf, detection_flag, detection_data, desherbage_actif, t_fin_desherbage

    while True:
        ret, frame = camera.read()
        if not ret:
            continue

        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        data = buffer.tobytes()

        try:
            with socket_lock:
                client.sendall(struct.pack('>I', len(data)))
                client.sendall(data)
                while b'\n' not in buf:
                    buf += client.recv(64)
                ligne, buf = buf.split(b'\n', 1)

            reponse = ligne.decode().strip()

            en_cooldown = (time.time() - t_fin_desherbage) < COOLDOWN_SEC
            if reponse != '0' and not desherbage_actif and not en_cooldown:
                parts = reponse.split(',')
                cx, cy = int(parts[0]), int(parts[1])
                hauteur = float(parts[2])
                with detection_lock:
                    detection_flag = True
                    detection_data = (cx, cy, hauteur)

        except Exception as e:
            print(f"Erreur socket : {e}")
            break

        time.sleep(0.05)


def detecter_bleu(frame):
    blurred = cv2.GaussianBlur(frame, (7, 7), 0)
    hsv = cv2.cvtColor(blurred, cv2.COLOR_BGR2HSV)
    masque1 = cv2.inRange(hsv, HSV_BAS, HSV_HAUT)
    masque2 = cv2.inRange(hsv, HSV_BAS2, HSV_HAUT2)
    masque = masque1 | masque2
    masque = cv2.erode(masque, None, iterations=2)
    masque = cv2.dilate(masque, None, iterations=3)
    contours, _ = cv2.findContours(masque, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 500:
        return None
    M = cv2.moments(c)
    if M['m00'] == 0:
        return None
    return int(M['m10'] / M['m00'])


def lire_cx_stable(n=3):
    mesures = []
    for _ in range(n * 4):
        ret, frame = camera.read()
        if not ret:
            continue
        cx = detecter_bleu(frame)
        if cx is not None:
            mesures.append(cx)
        if len(mesures) >= n:
            break
        time.sleep(0.05)
    return int(np.median(mesures)) if mesures else None


def desherber():
    global desherbage_actif, t_fin_desherbage
    s1 = S1_TRAVAIL
    print("\n*** DESHERBAGE : centrage objet bleu ***")

    frames_ok = 0
    for _ in range(40):
        time.sleep(0.5)
        cx = lire_cx_stable()
        if cx is None:
            print("Objet non visible")
            continue
        ex = cx - CX_IMAGE
        print(f"cx={cx:3d} | eX={ex:+4d} | s1={s1}")
        if abs(ex) < SEUIL_X:
            frames_ok += 1
            if frames_ok >= 3:
                print("Centrage confirme !")
                break
        else:
            frames_ok = 0
            s1 = max(S1_MIN, min(S1_MAX, int(s1 - KP_X * ex)))
            sc.set_angle(1, s1)

    print("Ouverture pince...")
    sc.set_angle(4, 130);             time.sleep(1)
    print("Descente bras...")
    sc.set_angle(2, 170)
    sc.set_angle(3, 130);             time.sleep(1.5)
    print("Fermeture pince...")
    sc.set_angle(4, 70);              time.sleep(1)
    sw.switch(1, 1); sw.switch(2, 1); time.sleep(0.8)
    sw.switch(1, 0); sw.switch(2, 0)
    print("Remontee bras...")
    sc.set_angle(2, 90)
    sc.set_angle(3, 90);              time.sleep(1.5)
    print("Servo 4 -> 170...")
    sc.set_angle(4, 170);             time.sleep(2)
    print("Servo 4 -> 90...")
    sc.set_angle(4, 90);              time.sleep(2)
    buzzer.play("C4"); time.sleep(0.8); buzzer.stop()
    print("Desherbage termine !")

    sc.set_angle(1, S1_TRAVAIL)
    sc.set_angle(2, S2_TRAVAIL)

    # Pause 3s + capture photo de verification
    print("Pause 3s : capture photo de verification...")
    time.sleep(1)
    ret, frame = camera.read()
    if ret:
        _, buf_img = cv2.imencode('.jpg', frame)
        try:
            requests.post(f'http://{PC_IP}:5000/save_verification',
                          data=buf_img.tobytes(),
                          headers={'Content-Type': 'image/jpeg'},
                          timeout=5)
            print("Photo de verification envoyee au PC !")
        except Exception as e:
            print(f"Erreur envoi photo : {e}")
    time.sleep(2)

    print("Robot reprend le trajet...")


def avancer(distance_cm, vitesse=5):
    global desherbage_actif, detection_flag, detection_data
    duree = distance_cm * 0.625
    sc.set_angle(0, 90)
    time.sleep(0.3)
    debut = time.time()
    move.Motor(1, 1, vitesse)
    move.Motor(2, 1, vitesse)

    while time.time() - debut < duree:
        with detection_lock:
            if detection_flag and not desherbage_actif:
                detection_flag = False
                move.motorStop()

                # Pause chrono
                t_arret = time.time()

                # 1. Pause 2s
                print("Mauvaise herbe detectee ! Pause 2s...")
                time.sleep(2)

                # 2. Avance 2cm
                print("Approche : avance 2cm...")
                sc.set_angle(0, 90)
                move.Motor(1, 1, vitesse)
                move.Motor(2, 1, vitesse)
                time.sleep(2 * 0.625)
                move.motorStop()

                # 3. Pause 2s
                print("Pause 2s avant arrachage...")
                time.sleep(2)

                # 4. Désherbage
                desherbage_actif = True
                desherber()

                # Compense le temps d'arrachage dans le chrono
                debut += (time.time() - t_arret)

                # Redemarrage moteurs
                sc.set_angle(0, 90)
                time.sleep(0.3)
                move.Motor(1, 1, vitesse)
                move.Motor(2, 1, vitesse)

                # Attente 15s avant reactivation detection
                time.sleep(15)
                t_fin_desherbage = time.time()
                desherbage_actif = False
                try:
                    requests.get(f'http://{PC_IP}:5000/activer_detection', timeout=2)
                    print("Detection reactivee !")
                except:
                    pass
        time.sleep(0.1)

    move.motorStop()
    time.sleep(0.3)


def tourner_gauche(duree_s=22.5):
    sc.set_angle(0, 45)
    time.sleep(0.5)
    move.Motor(1, 1, 5)
    move.Motor(2, 1, 5)
    time.sleep(duree_s)
    move.motorStop()
    sc.set_angle(0, 90)
    time.sleep(0.5)


def position_initiale():
    move.motorStop()
    for i in range(8):
        sc.set_angle(i, 90)
    sw.set_all_switch_off()
    time.sleep(1)


def trajet():
    print("Attente 2s..."); time.sleep(2)
    print("Position de travail : Servo1=135 Servo2=125...")
    sc.set_angle(1, S1_TRAVAIL)
    sc.set_angle(2, S2_TRAVAIL)
    time.sleep(1)

    print("Segment unique : Avance 90cm..."); avancer(90)

    print("Retour position initiale...")
    position_initiale()
    print("Mission terminee !")


# ── Lancement ──
print("Position initiale...")
for i in range(8):
    sc.set_angle(i, 90)
sw.set_all_switch_off()
time.sleep(1)

threading.Thread(target=thread_camera, daemon=True).start()
t_trajet = threading.Thread(target=trajet, daemon=True)
t_trajet.start()

try:
    t_trajet.join()
except KeyboardInterrupt:
    print("Arret")

camera.release()
client.close()
move.destroy()
