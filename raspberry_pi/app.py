#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BACKEND GATEWAY: FLASK + THREADING SERIAL (USB & BLUETOOTH HC-05)
Tich hop tinh Diem suong, Toc do tang nhiet, Nhat ky su co & API RFID
"""

import os
import time
import json
import math
import logging
import threading
from collections import deque

import serial
import serial.tools.list_ports
from flask import Flask, jsonify, request, render_template

import database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("smart_monitor")

app = Flask(__name__)

# Bo nho dem trang thai hien tai
latest_telemetry = {
    "temp": 0.0,
    "hum": 0.0,
    "rack": 0.0,
    "dew_point": 0.0,
    "rise_rate": 0.0,
    "door": "CLOSED",
    "light": "OFF",
    "thresh": 30.0,
    "status": "DISCONNECTED",
    "servo": 0,
    "conn_type": "NONE",
    "last_update": "--:--:--",
}

data_lock = threading.Lock()
serial_lock = threading.Lock()
serial_port_instance = None

# Hang doi tinh toc do tang nhiet (Luu 5 mau gan nhat: (timestamp_sec, rack_temp))
temp_window = deque(maxlen=5)
last_recorded_status = "NORMAL"

VALID_COMMANDS = {"VENT_OPEN", "VENT_CLOSE", "VENT_AUTO", "ALARM_OFF"}

# Danh sach nhan vien dang ky the RFID mau
RFID_DIRECTORY = {
    "A1B2C3D4": "Nguyen Van An (SysAdmin)",
    "E5F6G7H8": "Tran Minh Tuan (Ky su Mang)",
    "99887766": "Le Hoang Nam (Bao tri)",
}


def calculate_dew_point(temp_c, hum_pct):
    """Tinh diem suong (C) theo cong thuc Magnus-Tetens"""
    if not hum_pct or hum_pct <= 0 or temp_c is None:
        return 0.0
    a, b = 17.27, 237.7
    gamma = ((a * temp_c) / (b + temp_c)) + math.log(hum_pct / 100.0)
    dew = (b * gamma) / (a - gamma)
    return round(dew, 1)


def calculate_rise_rate(current_rack_temp):
    """Tinh toc do bien thien nhiet do tu Rack (C/phut)"""
    now = time.time()
    temp_window.append((now, current_rack_temp))
    if len(temp_window) < 2:
        return 0.0
    oldest_t, oldest_temp = temp_window[0]
    dt_minutes = (now - oldest_t) / 60.0
    if dt_minutes <= 0.01:
        return 0.0
    rate = (current_rack_temp - oldest_temp) / dt_minutes
    return round(rate, 2)


def find_communication_port():
    """Uu tien quet cong USB Serial Arduino hoac Bluetooth RFCOMM0"""
    if os.path.exists("/dev/rfcomm0"):
        return "/dev/rfcomm0", "BLUETOOTH (HC-05)"

    ports = list(serial.tools.list_ports.comports())
    for p in ports:
        desc = (p.description or "").lower()
        dev = p.device
        if any(k in desc for k in ["arduino", "ch340", "cp210", "usb serial"]) or "ttyacm" in dev.lower() or "ttyusb" in dev.lower():
            return dev, f"USB SERIAL ({dev})"
    return None, "NONE"


def serial_worker():
    """Luong nen doc JSON tu Arduino, tinh toan phan tich & ghi SQLite"""
    global serial_port_instance, last_recorded_status

    log.info("Serial worker thread started, scanning for Arduino/Bluetooth...")

    while True:
        port, conn_label = find_communication_port()
        if not port:
            with data_lock:
                latest_telemetry["status"] = "DISCONNECTED"
                latest_telemetry["conn_type"] = "NONE"
            log.warning("Khong tim thay Arduino (USB) hoac HC-05 (/dev/rfcomm0) - thu lai sau 3s")
            time.sleep(3)
            continue

        try:
            log.info("Dang ket noi qua %s", conn_label)
            ser = serial.Serial(port, 9600, timeout=2)
            with serial_lock:
                serial_port_instance = ser
            time.sleep(2.0)
            log.info("Da ket noi thanh cong qua %s", conn_label)
            database.insert_incident("INFO", f"Gateway da ket noi qua {conn_label}")

            while True:
                if ser.in_waiting > 0:
                    raw_line = ser.readline().decode("utf-8", errors="ignore").strip()
                    if raw_line.startswith("{") and raw_line.endswith("}"):
                        try:
                            payload = json.loads(raw_line)
                        except json.JSONDecodeError:
                            log.warning("Du lieu JSON khong hop le, bo qua: %r", raw_line)
                            continue

                        temp = float(payload.get("temp", 0.0))
                        hum = float(payload.get("hum", 0.0))
                        rack = float(payload.get("rack", 0.0))
                        status = payload.get("status", "NORMAL")
                        door = payload.get("door", "CLOSED")
                        light = payload.get("light", "OFF")
                        servo = int(payload.get("servo", 0))

                        dew_pt = calculate_dew_point(temp, hum)
                        rise_rt = calculate_rise_rate(rack)

                        if status != last_recorded_status:
                            if status == "CRITICAL":
                                database.insert_incident(
                                    "CRITICAL",
                                    f"Qua nhiet tu Rack ({rack}C - coi nhu >60C)! Kich hoat quat 100%.",
                                )
                            elif status == "WARNING":
                                database.insert_incident(
                                    "WARNING",
                                    f"Nhiet do cham nguong canh bao (Rack: {rack}C, Phong: {temp}C).",
                                )
                            elif status == "NORMAL" and last_recorded_status in ("WARNING", "CRITICAL"):
                                database.insert_incident("INFO", "Nhiet do he thong da hoi phuc ve muc an toan.")
                            log.info("EVENT STATUS_CHANGE %s -> %s", last_recorded_status, status)
                            last_recorded_status = status

                        with data_lock:
                            latest_telemetry.update(payload)
                            latest_telemetry["dew_point"] = dew_pt
                            latest_telemetry["rise_rate"] = rise_rt
                            latest_telemetry["conn_type"] = conn_label
                            latest_telemetry["last_update"] = time.strftime("%H:%M:%S")

                        database.insert_log(temp, hum, rack, dew_pt, rise_rt, door, light, status, servo)

                        log.info(
                            "READING temp=%.1fC hum=%.1f%% rack=%.1fC dew=%.1fC rise=%.2fC/p "
                            "door=%s light=%s status=%s servo=%s",
                            temp, hum, rack, dew_pt, rise_rt, door, light, status, servo,
                        )
                time.sleep(0.05)

        except (serial.SerialException, OSError) as exc:
            log.error("Mat ket noi %s: %s", port, exc)
            with serial_lock:
                serial_port_instance = None
            with data_lock:
                latest_telemetry["status"] = "DISCONNECTED"
                latest_telemetry["conn_type"] = "NONE"
            database.insert_incident("WARNING", f"Mat ket noi Serial tren {port}: {exc}")
            time.sleep(2)


def send_command_to_arduino(cmd):
    with serial_lock:
        if serial_port_instance and serial_port_instance.is_open:
            try:
                serial_port_instance.write((cmd + "\n").encode("utf-8"))
                serial_port_instance.flush()
                log.info("Da gui lenh xuong Arduino: %s", cmd)
                return True, f"Da thuc thi lenh '{cmd}'."
            except Exception as exc:
                log.error("Gui lenh '%s' loi: %s", cmd, exc)
                return False, str(exc)
        log.error("Khong gui duoc lenh '%s': chua ket noi Arduino", cmd)
        return False, "Chua ket noi duoc voi Arduino!"


# --- FLASK API ROUTES ---

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/data/current", methods=["GET"])
def api_current():
    with data_lock:
        return jsonify(latest_telemetry)


@app.route("/api/data/history", methods=["GET"])
def api_history():
    return jsonify(database.get_history_logs(limit=20))


@app.route("/api/incidents", methods=["GET"])
def api_incidents():
    return jsonify(database.get_recent_incidents(limit=10))


@app.route("/api/rfid", methods=["GET", "POST"])
def api_rfid():
    """API doc danh sach ra vao hoac ghi nhan quet the RFID moi"""
    if request.method == "GET":
        return jsonify(database.get_recent_access_logs(limit=8))

    data = request.get_json(silent=True) or {}
    uid = str(data.get("uid", "A1B2C3D4")).upper()
    staff = RFID_DIRECTORY.get(uid, f"Khach vang lai ({uid})")
    database.insert_rfid_access(uid, staff, "QUET THE VAO PHONG")
    database.insert_incident("INFO", f"Nhan su [{staff}] vua mo khoa vao phong Server.")
    log.info("RFID scan: uid=%s staff=%s", uid, staff)
    return jsonify({"success": True, "uid": uid, "staff": staff})


@app.route("/api/control", methods=["POST"])
def api_control():
    data = request.get_json(silent=True) or {}
    cmd = str(data.get("command", "")).strip().upper()
    if cmd not in VALID_COMMANDS:
        log.warning("Tu choi lenh dieu khien khong hop le: %r", cmd)
        return jsonify({"success": False, "message": "Lenh khong hop le!"}), 400

    ok, msg = send_command_to_arduino(cmd)
    if ok:
        database.insert_incident("INFO", f"Quan tri vien gui lenh dieu khien tu xa: {cmd}")
    return jsonify({"success": ok, "message": msg})


if __name__ == "__main__":
    log.info("=== Smart Server Room Monitoring Gateway dang khoi dong ===")
    database.init_db()
    t = threading.Thread(target=serial_worker, daemon=True)
    t.start()
    log.info("Web Dashboard san sang tai: http://0.0.0.0:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
