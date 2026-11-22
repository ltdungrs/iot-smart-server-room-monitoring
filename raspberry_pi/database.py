#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DATABASE MODULE: SQLITE3 (iot_monitor.db)
Gồm 3 bảng: logs (cảm biến), incidents (nhật ký sự cố), access_logs (thẻ RFID vào phòng)
"""

import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "iot_monitor.db")


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Bảng nhật ký thông số môi trường
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
            temp REAL,
            hum REAL,
            rack REAL,
            dew_point REAL,
            rise_rate REAL,
            door TEXT,
            light TEXT,
            status TEXT,
            servo_state INTEGER
        )
    ''')

    # 2. Bảng ghi nhận sự cố (Ý tưởng mở rộng)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
            severity TEXT,
            message TEXT
        )
    ''')

    # 3. Bảng điểm danh ra vào phòng bằng thẻ RFID (Ý tưởng mở rộng)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS access_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT (datetime('now', 'localtime')),
            card_uid TEXT,
            staff_name TEXT,
            action TEXT
        )
    ''')

    conn.commit()
    conn.close()
    print(f"[DATABASE] Da khoi tao thanh cong CSDL '{DB_NAME}'.")


def insert_log(temp, hum, rack, dew_point, rise_rate, door, light, status, servo_state):
    try:
        conn = get_db_connection()
        conn.execute('''
            INSERT INTO logs (temp, hum, rack, dew_point, rise_rate, door, light, status, servo_state)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (temp, hum, rack, dew_point, rise_rate, door, light, status, servo_state))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB ERROR] {e}")


def insert_incident(severity, message):
    try:
        conn = get_db_connection()
        conn.execute('INSERT INTO incidents (severity, message) VALUES (?, ?)', (severity, message))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB INCIDENT ERROR] {e}")


def insert_rfid_access(card_uid, staff_name, action="ENTER SERVER ROOM"):
    try:
        conn = get_db_connection()
        conn.execute('INSERT INTO access_logs (card_uid, staff_name, action) VALUES (?, ?, ?)',
                     (card_uid, staff_name, action))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[DB RFID ERROR] {e}")


def get_history_logs(limit=20):
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM (SELECT * FROM logs ORDER BY id DESC LIMIT ?) ORDER BY id ASC', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_incidents(limit=10):
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM incidents ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_recent_access_logs(limit=8):
    conn = get_db_connection()
    rows = conn.execute('SELECT * FROM access_logs ORDER BY id DESC LIMIT ?', (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_db_stats():
    """Dem so dong & id moi nhat cua tung bang - de dashboard hien thi ghi DB lien tuc."""
    conn = get_db_connection()
    stats = {}
    for table in ("logs", "incidents", "access_logs"):
        row = conn.execute(f"SELECT COUNT(*) AS c, MAX(id) AS last_id FROM {table}").fetchone()
        stats[table] = {"count": row["c"] or 0, "last_id": row["last_id"]}
    conn.close()
    return stats


if __name__ == "__main__":
    init_db()
