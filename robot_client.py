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

# Centre image
CX_IMAGE = 320
CY_IMAGE = 240

# Limites servos
S1_MIN, S1_MAX = 40, 180   # axe horizontal (gauche/droite)
S2_MIN, S2_MAX = 90, 170   # axe vertical (haut/bas)
S3_MIN, S3_MAX = 40, 140   # axe profondeur

# Position de travail (bras pointé vers le sol)
S1_WORK = 145
S2_WORK = 130
S3_WORK = 90

# Seuil de convergence en pixels
SEUIL_X = 30
SEUIL_Y = 30
MAX_ITER = 15

# Gains IBVS (petits pour éviter la saturation)
GAIN_S1 = 0.08   # servo1 contrôle X (horizontal)
GAIN_S2 = 0.10   # servo2 contrôle Y (vertical)
GAIN_S3 = 0.04   # servo3 aide la profondeur

arrachage_en_cours = False
detection_lock = threading.Lock()

# ── Socket et caméra (globaux pour accès depuis IBVS) ──
client = None
camera = None
buf = b''


def envoyer_frame_et_recevoir():
    """Envoie une frame et retourne (cx, cy) ou None."""
    global buf
    ret, frame = camera.read()
    if not ret:
        return None

    _, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    data = buffer.tobytes()
    client.sendall(struct.pack('>I', len(data)))
    client.sendall(data)

    # Lire réponse avec timeout
    client.settimeout(2.0)
    try:
        while b'\n' not in buf:
            chunk = client.recv(64)
            if not chunk:
                return None
            buf += chunk
        ligne, buf = buf.split(b'\n', 1)
        reponse = ligne.decode().strip()
    except socket.timeout:
        return None
    finally:
        client.settimeout(None)

    if reponse == '0':
        return None
    try:
        cx, cy, hauteur = reponse.split(',')
        return int(cx), int(cy), float(hauteur)
    except:
        return None


def buzzer_c4():
    buzzer.play("C4")
    time.sleep(1)
    buzzer.stop()


def arracher():
    """Séquence d'arrachage : ouvre dents → ferme → retour position travail."""
    print("Arrachage...")
    threading.Thread(target=buzzer_c4, daemon=True).start()
    time.sleep(1)

    print("Dents ouvrent...")
    sc.set_angle(4, 130)
    time.sleep(1.5)

    print("Dents ferment...")
    sc.set_angle(4, 80)
    time.sleep(1.5)

    sw.switch(1, 1)
    sw.switch(2, 1)
    time.sleep(0.8)
    sw.switch(1, 0)
    sw.switch(2, 0)
    time.sleep(0.5)

    print("Retour position parcours...")
    sc.set_angle(3, S3_WORK)
    time.sleep(1.5)
    sc.set_angle(4, 90)
    time.sleep(0.8)
    sc.set_angle(2, 90)
    time.sleep(0.8)
    sc.set_angle(2, S2_WORK)
    time.sleep(0.8)
    sc.set_angle(1, S1_WORK)
    time.sleep(1.5)

    try:
        requests.get(f'http://{PC_IP}:5000/activer_detection', timeout=2)
        print("Detection reactivee !")
    except:
        pass
    print("Arrachage termine ! Robot continue...")


def boucle_ibvs():
    """
    Boucle IBVS synchrone :
    - Envoie une frame, reçoit cx/cy du PC
    - Calcule l'erreur par rapport au centre image
    - Ajuste les servos proportionnellement
    - Répète jusqu'à convergence ou MAX_ITER
    """
    global arrachage_en_cours

    s1 = S1_WORK
    s2 = S2_WORK
    s3 = S3_WORK

    print("Boucle IBVS demarre...")

    for iteration in range(MAX_ITER):
        print(f"IBVS iteration {iteration+1}/{MAX_ITER}")

        # Attendre que les servos finissent de bouger
        time.sleep(0.6)

        # Envoyer frame et recevoir coordonnées
        result = envoyer_frame_et_recevoir()

        if result is None:
            print("Timeout coord - on continue...")
            continue

        cx, cy, hauteur = result
        print(f"Coord recues cx={cx} cy={cy}")

        erreur_x = cx - CX_IMAGE
        erreur_y = cy - CY_IMAGE
        print(f"Erreur X={erreur_x} Y={erreur_y}")

        # Convergence atteinte ?
        if abs(erreur_x) < SEUIL_X and abs(erreur_y) < SEUIL_Y:
            print("Converge ! Lancement arrachage...")
            break

        # ── Ajustement servo 1 : axe X (horizontal) ──
        # erreur_x > 0 → herbe à droite → augmenter s1
        delta_s1 = erreur_x * GAIN_S1
        s1 = int(s1 + delta_s1)
        s1 = max(S1_MIN, min(S1_MAX, s1))
        print(f"Servo1={s1}")
        sc.set_angle(1, s1)

        # ── Ajustement servo 2 : axe Y (vertical) ──
        # erreur_y > 0 → herbe en bas → augmenter s2 (bras descend)
        delta_s2 = erreur_y * GAIN_S2
        s2 = int(s2 + delta_s2)
        s2 = max(S2_MIN, min(S2_MAX, s2))
        print(f"Servo2={s2}")
        sc.set_angle(2, s2)

        # ── Ajustement servo 3 : profondeur ──
        delta_s3 = erreur_x * GAIN_S3
        s3 = int(s3 + delta_s3)
        s3 = max(S3_MIN, min(S3_MAX, s3))
        print(f"Servo3={s3}")
        sc.set_angle(3, s3)

    arracher()
    arrachage_en_cours = False


def avancer(distance_cm, vitesse=5):
    global arrachage_en_cours
    duree = distance_cm * 0.625
    sc.set_angle(0, 90)
    time.sleep(0.3)

    debut = time.time()
    move.Motor(1, 1, vitesse)
    move.Motor(2, 1, vitesse)

    while time.time() - debut < duree:
        if arrachage_en_cours:
            # Attendre fin arrachage
            while arrachage_en_cours:
                time.sleep(0.2)
            # Reprendre
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

    print(f"Servo 1 -> {S1_WORK}...")
    sc.set_angle(1, S1_WORK)
    time.sleep(2)

    print(f"Servo 2 -> {S2_WORK}...")
    sc.set_angle(2, S2_WORK)
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


# ── Initialisation ──
print("Position initiale...")
for i in range(8):
    sc.set_angle(i, 90)
sw.set_all_switch_off()
time.sleep(1)

client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client.connect((PC_IP, PORT))
print("Connecte au PC")

camera = cv2.VideoCapture(0)
camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
time.sleep(1)
print("Live en cours...")

t_trajet = threading.Thread(target=trajet, daemon=True)
t_trajet.start()

try:
    while True:
        # Si IBVS en cours, la boucle IBVS gère elle-même les frames
        if arrachage_en_cours:
            time.sleep(0.1)
            continue

        result = envoyer_frame_et_recevoir()

        if result is not None and not arrachage_en_cours:
            cx, cy, hauteur = result
            print(f"Detection ! cx={cx} cy={cy}")
            move.motorStop()
            time.sleep(0.3)
            arrachage_en_cours = True
            # Lancer IBVS dans un thread (non-bloquant pour la boucle principale)
            threading.Thread(target=boucle_ibvs, daemon=True).start()

        time.sleep(0.1)

except KeyboardInterrupt:
    print("Arret")

camera.release()
client.close()
move.destroy()
