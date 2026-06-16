import sys
sys.path.append('/home/kit12/adeept_picar-pro/Server')

import socket
import struct
import cv2
import time
import threading
import requests
import Move as move
from RPIservo import ServoCtrl
from gpiozero import TonalBuzzer
import Switch as sw

PC_IP = '10.116.177.105'
PORT  = 9999

buzzer = TonalBuzzer(18)
move.setup()
sc = ServoCtrl()
sw.switchSetup()

CX_IMAGE = 320
CY_IMAGE = 240
S1_MIN = 40
S1_MAX = 180
S2_MIN = 90
S2_MAX = 170
S3_MIN = 40
S3_MAX = 140

s1_angle = 145
s2_angle = 130
s3_angle = 90

SEUIL_X = 40
SEUIL_Y = 40
MAX_ITER = 10

arrachage_fait = False
mode_ibvs = False
derniere_coord = None
detection_flag = False
detection_data = None
detection_lock = threading.Lock()
ibvs_lock = threading.Lock()

def buzzer_c4():
    buzzer.play("C4")
    time.sleep(1)
    buzzer.stop()

def arracher():
    global s1_angle, s2_angle, s3_angle, arrachage_fait, mode_ibvs
    print("Arrachage...")

    threading.Thread(target=buzzer_c4).start()
    time.sleep(2)

    print("Dents ouvrent...")
    sc.set_angle(4, 130)
    time.sleep(2)

    print("Dents ferment...")
    sc.set_angle(4, 80)
    time.sleep(2)

    sw.switch(1, 1)
    sw.switch(2, 1)
    time.sleep(1)
    sw.switch(1, 0)
    sw.switch(2, 0)
    time.sleep(1)

    print("Retour position parcours...")
    sc.set_angle(3, 90)
    s3_angle = 90
    time.sleep(2)
    sc.set_angle(4, 90)
    time.sleep(1)
    sc.set_angle(2, 90)
    time.sleep(1)
    sc.set_angle(2, 130)
    s2_angle = 130
    time.sleep(1)
    sc.set_angle(1, 145)
    s1_angle = 145
    time.sleep(2)

    mode_ibvs = False
    arrachage_fait = False

    try:
        requests.get(f'http://{PC_IP}:5000/activer_detection', timeout=2)
        print("Detection reactivee !")
    except:
        pass

    print("Arrachage termine ! Robot continue...")

def boucle_ibvs():
    global s1_angle, s2_angle, s3_angle
    global arrachage_fait, mode_ibvs, derniere_coord

    print("Boucle IBVS demarre...")

    for iteration in range(MAX_ITER):
        print(f"IBVS iteration {iteration+1}/{MAX_ITER}")

        # Attendre nouvelles coordonnees
        timeout = time.time() + 3
        while time.time() < timeout:
            with ibvs_lock:
                if derniere_coord is not None:
                    cx, cy = derniere_coord
                    derniere_coord = None
                    break
            time.sleep(0.1)
        else:
            print("Timeout coord - on continue...")
            continue

        print(f"Coord cx={cx} cy={cy}")

        erreur_x = cx - CX_IMAGE
        erreur_y = cy - CY_IMAGE
        print(f"Erreur X={erreur_x} Y={erreur_y}")

        # Convergence atteinte
        if abs(erreur_x) < SEUIL_X and abs(erreur_y) < SEUIL_Y:
            print("Converge ! Arrachage...")
            break

        # Ajuste servo 1 axe X
        if abs(erreur_x) > SEUIL_X:
            delta_s1 = erreur_x * 0.25
            s1_new = int(s1_angle + delta_s1)
            s1_new = max(S1_MIN, min(S1_MAX, s1_new))
            print(f"Servo1={s1_new}")
            sc.set_angle(1, s1_new)
            s1_angle = s1_new
            time.sleep(0.8)

        # Ajuste servo 2 axe Y
        if abs(erreur_y) > SEUIL_Y:
            delta_s2 = erreur_y * 0.5
            s2_new = int(s2_angle + delta_s2)
            s2_new = max(S2_MIN, min(S2_MAX, s2_new))
            print(f"Servo2={s2_new}")
            sc.set_angle(2, s2_new)
            s2_angle = s2_new
            time.sleep(0.5)

        # Ajuste servo 3
        delta_s3 = erreur_x * 0.5
        s3_new = int(s3_angle + delta_s3)
        s3_new = max(S3_MIN, min(S3_MAX, s3_new))
        print(f"Servo3={s3_new}")
        sc.set_angle(3, s3_new)
        s3_angle = s3_new
        time.sleep(0.5)

    # Arracher
    arrachage_fait = True
    arracher()

def avancer(distance_cm, vitesse=5):
    global arrachage_fait, detection_flag, detection_data
    global mode_ibvs, derniere_coord
    duree = distance_cm * 0.625
    sc.set_angle(0, 90)
    time.sleep(0.3)

    debut = time.time()
    move.Motor(1, 1, vitesse)
    move.Motor(2, 1, vitesse)

    while time.time() - debut < duree:
        with detection_lock:
            if detection_flag and not arrachage_fait and not mode_ibvs:
                detection_flag = False
                cx, cy, hauteur = detection_data
                move.motorStop()
                time.sleep(0.3)
                mode_ibvs = True
                with ibvs_lock:
                    derniere_coord = (cx, cy)
                threading.Thread(target=boucle_ibvs).start()
                while mode_ibvs or arrachage_fait:
                    time.sleep(0.2)
                sc.set_angle(0, 90)
                time.sleep(0.3)
                move.Motor(1, 1, vitesse)
                move.Motor(2, 1, vitesse)
        time.sleep(0.1)

    move.motorStop()
    time.sleep(0.3)

def tourner_gauche():
    sc.set_angle(0, 45)
    time.sleep(0.5)
    move.Motor(1, 1, 5)
    move.Motor(2, 1, 5)
    time.sleep(19)
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
    print("Attente 2s...")
    time.sleep(2)

    print("Servo 1 -> 145...")
    sc.set_angle(1, 145)
    time.sleep(2)

    print("Servo 2 -> 130...")
    sc.set_angle(2, 130)
    time.sleep(1)

    print("Avance 75cm...")
    avancer(75)

    print("Tourne gauche 19s...")
    tourner_gauche()

    print("Avance 60cm...")
    avancer(60)

    print("Tourne gauche 19s...")
    tourner_gauche()

    print("Avance 70cm...")
    avancer(70)

    print("Retour position initiale...")
    position_initiale()
    print("Mission terminee !")

# Position initiale
print("Position initiale...")
for i in range(8):
    sc.set_angle(i, 90)
sw.set_all_switch_off()
time.sleep(1)

# Connexion PC
client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((PC_IP, PORT))
print("Connecte au PC")

# Camera
camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
time.sleep(1)
print("Live en cours...")

# Lancer trajet
t_trajet = threading.Thread(target=trajet)
t_trajet.daemon = True
t_trajet.start()

buf = b''

try:
    while True:
        ret, frame = camera.read()
        if not ret:
            continue

        _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        data = buffer.tobytes()

        client.sendall(struct.pack('>I', len(data)))
        client.sendall(data)

        while b'\n' not in buf:
            buf += client.recv(64)
        ligne, buf = buf.split(b'\n', 1)
        reponse = ligne.decode().strip()

        if reponse != '0':
            try:
                cx, cy, hauteur = reponse.split(',')
                cx, cy = int(cx), int(cy)
                if not mode_ibvs and not arrachage_fait:
                    with detection_lock:
                        detection_flag = True
                        detection_data = (cx, cy, float(hauteur))
                elif mode_ibvs:
                    with ibvs_lock:
                        derniere_coord = (cx, cy)
            except:
                pass

        time.sleep(0.1)

except KeyboardInterrupt:
    print("Arret")

camera.release()
client.close()
move.destroy()