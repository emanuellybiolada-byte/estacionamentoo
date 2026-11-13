#!/usr/bin/env python3
"""
Sistema de Estacionamento - Arquivo único
"""

import json
import sqlite3
from datetime import datetime
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from pathlib import Path

# ==================== BANCO DE DADOS ====================

DB_PATH = Path(__file__).parent / "parking.db"

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            document TEXT UNIQUE,
            phone TEXT,
            email TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vehicles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER,
            plate TEXT NOT NULL UNIQUE,
            brand TEXT,
            model TEXT,
            color TEXT,
            year INTEGER,
            type TEXT DEFAULT 'carro',
            size TEXT DEFAULT 'medio',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (client_id) REFERENCES clients(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            number TEXT NOT NULL UNIQUE,
            type TEXT DEFAULT 'normal',
            status TEXT DEFAULT 'livre',
            current_vehicle_id INTEGER,
            FOREIGN KEY (current_vehicle_id) REFERENCES vehicles(id) ON DELETE SET NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS tariffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            vehicle_type TEXT DEFAULT 'todos',
            period TEXT NOT NULL,
            price REAL NOT NULL,
            description TEXT,
            active INTEGER DEFAULT 1
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS parking_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vehicle_id INTEGER NOT NULL,
            spot_id INTEGER NOT NULL,
            entry_time TEXT NOT NULL,
            exit_time TEXT,
            calculated_price REAL DEFAULT 0,
            status TEXT DEFAULT 'ativo',
            notes TEXT,
            FOREIGN KEY (vehicle_id) REFERENCES vehicles(id),
            FOREIGN KEY (spot_id) REFERENCES spots(id)
        )
    """)

    conn.commit()

    cur.execute("SELECT COUNT(*) FROM spots")
    if cur.fetchone()[0] == 0:
        seed_data(conn)

    conn.close()

def seed_data(conn):
    cur = conn.cursor()

    spots = []
    for i in range(1, 13):
        spots.append((f"A{i:02d}", "normal"))
    for i in range(1, 5):
        spots.append((f"P{i:02d}", "preferencial"))
    for i in range(1, 3):
        spots.append((f"I{i:02d}", "idoso"))
    for i in range(1, 3):
        spots.append((f"D{i:02d}", "deficiente"))

    cur.executemany("INSERT INTO spots (number, type) VALUES (?, ?)", spots)

    tariffs = [
        ("Hora Carro", "carro", "hora", 12.00, "Cobrança por hora ou fração"),
        ("Hora Moto", "moto", "hora", 6.00, "Cobrança por hora ou fração"),
        ("Diária Carro", "carro", "diaria", 45.00, "Pernoite / diária"),
        ("Diária Moto", "moto", "diaria", 25.00, "Pernoite / diária"),
        ("Mensal Carro", "carro", "mensal", 350.00, "Assinatura mensal"),
        ("Anual Carro", "carro", "anual", 3500.00, "Assinatura anual"),
        ("Hora Caminhão", "caminhao", "hora", 25.00, "Veículos grandes"),
    ]
    cur.executemany(
        "INSERT INTO tariffs (name, vehicle_type, period, price, description) VALUES (?, ?, ?, ?, ?)",
        tariffs
    )

    cur.execute(
        "INSERT INTO clients (name, document, phone, email) VALUES (?, ?, ?, ?)",
        ("João da Silva", "123.456.789-00", "(41) 99999-8888", "joao@email.com")
    )
    client_id = cur.lastrowid

    cur.execute(
        """INSERT INTO vehicles (client_id, plate, brand, model, color, year, type, size)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (client_id, "ABC1D23", "Toyota", "Corolla", "Prata", 2022, "carro", "medio")
    )

    conn.commit()
    print("✓ Dados iniciais inseridos")

def calculate_price(vehicle_type, entry_time, exit_time=None):
    if exit_time is None:
        exit_time = datetime.now().isoformat()

    entry = datetime.fromisoformat(entry_time)
    exit_ = datetime.fromisoformat(exit_time)
    diff = (exit_ - entry).total_seconds()
    hours = max(1, int(diff / 3600) + (1 if diff % 3600 > 0 else 0))

    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """SELECT price FROM tariffs
           WHERE active = 1 AND period = 'hora'
             AND (vehicle_type = ? OR vehicle_type = 'todos')
           ORDER BY CASE WHEN vehicle_type = ? THEN 0 ELSE 1 END
           LIMIT 1""",
        (vehicle_type, vehicle_type)
    )
    row = cur.fetchone()
    conn.close()

    price_per_hour = row["price"] if row else 12.0
    return round(price_per_hour * hours, 2)

def list_from_rows(rows):
    return [dict(r) for r in rows]

# ==================== SERVIDOR ====================

FRONTEND_DIR = Path(__file__).parent / "frontend"
PORT = 8000

class ParkingHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(FRONTEND_DIR), **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path.startswith("/api/"):
            self.handle_api_get(path, parse_qs(parsed.query))
        else:
            if path == "/" or path == "":
                self.path = "/index.html"
            super().do_GET()

    def do_POST(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json({"error": "JSON inválido"}, 400)
                return
            self.handle_api_post(parsed.path, data)
        else:
            self.send_error(404)

    def do_PUT(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8") if content_length else "{}"
            try:
                data = json.loads(body) if body else {}
            except json.JSONDecodeError:
                self.send_json({"error": "JSON inválido"}, 400)
                return
            self.handle_api_put(parsed.path, data)
        else:
            self.send_error(404)

    def do_DELETE(self):
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            self.handle_api_delete(parsed.path)
        else:
            self.send_error(404)

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_api_get(self, path, query):
        conn = get_connection()
        cur = conn.cursor()

        try:
            if path == "/api/dashboard":
                cur.execute("SELECT COUNT(*) as total FROM spots")
                total_spots = cur.fetchone()["total"]

                cur.execute("SELECT COUNT(*) as ocupadas FROM spots WHERE status = 'ocupada'")
                occupied = cur.fetchone()["ocupadas"]

                cur.execute("SELECT COUNT(*) as ativos FROM parking_records WHERE status = 'ativo'")
                active = cur.fetchone()["ativos"]

                today = datetime.now().strftime("%Y-%m-%d")
                cur.execute(
                    """SELECT COALESCE(SUM(calculated_price), 0) as receita
                       FROM parking_records
                       WHERE status = 'finalizado' AND date(exit_time) = ?""",
                    (today,)
                )
                revenue_today = cur.fetchone()["receita"]

                month = datetime.now().strftime("%Y-%m")
                cur.execute(
                    """SELECT COALESCE(SUM(calculated_price), 0) as receita
                       FROM parking_records
                       WHERE status = 'finalizado' AND strftime('%Y-%m', exit_time) = ?""",
                    (month,)
                )
                revenue_month = cur.fetchone()["receita"]

                cur.execute("SELECT type, status, COUNT(*) as qtd FROM spots GROUP BY type, status")
                spots_by_type = list_from_rows(cur.fetchall())

                self.send_json({
                    "total_spots": total_spots,
                    "occupied": occupied,
                    "available": total_spots - occupied,
                    "active_vehicles": active,
                    "revenue_today": revenue_today,
                    "revenue_month": revenue_month,
                    "occupancy_rate": round((occupied / total_spots * 100) if total_spots else 0, 1),
                    "spots_by_type": spots_by_type
                })

            elif path == "/api/spots":
                cur.execute("""
                    SELECT s.*, v.plate, v.brand, v.model
                    FROM spots s
                    LEFT JOIN vehicles v ON s.current_vehicle_id = v.id
                    ORDER BY s.number
                """)
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/clients":
                cur.execute("SELECT * FROM clients ORDER BY name")
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/vehicles":
                cur.execute("""
                    SELECT v.*, c.name as client_name
                    FROM vehicles v
                    LEFT JOIN clients c ON v.client_id = c.id
                    ORDER BY v.plate
                """)
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/tariffs":
                cur.execute("SELECT * FROM tariffs WHERE active = 1 ORDER BY period, vehicle_type")
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/records":
                status = query.get("status", [None])[0]
                sql = """
                    SELECT r.*, v.plate, v.brand, v.model, v.type as vehicle_type,
                           s.number as spot_number, s.type as spot_type
                    FROM parking_records r
                    JOIN vehicles v ON r.vehicle_id = v.id
                    JOIN spots s ON r.spot_id = s.id
                """
                params = []
                if status:
                    sql += " WHERE r.status = ?"
                    params.append(status)
                sql += " ORDER BY r.entry_time DESC LIMIT 100"
                cur.execute(sql, params)
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/reports/revenue":
                cur.execute("""
                    SELECT date(exit_time) as dia, SUM(calculated_price) as total, COUNT(*) as qtd
                    FROM parking_records
                    WHERE status = 'finalizado' AND exit_time IS NOT NULL
                    GROUP BY date(exit_time)
                    ORDER BY dia DESC LIMIT 30
                """)
                self.send_json(list_from_rows(cur.fetchall()))

            elif path == "/api/reports/by-type":
                cur.execute("""
                    SELECT v.type, COUNT(*) as qtd, SUM(r.calculated_price) as receita
                    FROM parking_records r
                    JOIN vehicles v ON r.vehicle_id = v.id
                    WHERE r.status = 'finalizado'
                    GROUP BY v.type
                """)
                self.send_json(list_from_rows(cur.fetchall()))

            else:
                self.send_json({"error": "Rota não encontrada"}, 404)

        except Exception as e:
            self.send_json({"error": str(e)}, 500)
        finally:
            conn.close()

    def handle_api_post(self, path, data):
        conn = get_connection()
        cur = conn.cursor()

        try:
            if path == "/api/clients":
                cur.execute(
                    "INSERT INTO clients (name, document, phone, email) VALUES (?, ?, ?, ?)",
                    (data.get("name"), data.get("document"), data.get("phone"), data.get("email"))
                )
                conn.commit()
                self.send_json({"id": cur.lastrowid, "message": "Cliente cadastrado"}, 201)

            elif path == "/api/vehicles":
                plate = data.get("plate", "").upper().replace(" ", "").replace("-", "")
                if not plate:
                    self.send_json({"error": "Placa é obrigatória"}, 400)
                    return

                cur.execute("SELECT id FROM vehicles WHERE plate = ?", (plate,))
                if cur.fetchone():
                    self.send_json({"error": "Placa já cadastrada"}, 400)
                    return

                cur.execute(
                    """INSERT INTO vehicles (client_id, plate, brand, model, color, year, type, size)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        data.get("client_id"),
                        plate,
                        data.get("brand"),
                        data.get("model"),
                        data.get("color"),
                        data.get("year"),
                        data.get("type", "carro"),
                        data.get("size", "medio")
                    )
                )
                conn.commit()
                self.send_json({"id": cur.lastrowid, "message": "Veículo cadastrado"}, 201)

            elif path == "/api/entry":
                plate = data.get("plate", "").upper().replace(" ", "").replace("-", "")
                spot_id = data.get("spot_id")

                if not plate:
                    self.send_json({"error": "Placa obrigatória"}, 400)
                    return

                cur.execute("SELECT id, type FROM vehicles WHERE plate = ?", (plate,))
                vehicle = cur.fetchone()

                if not vehicle:
                    cur.execute(
                        "INSERT INTO vehicles (plate, type) VALUES (?, ?)",
                        (plate, data.get("type", "carro"))
                    )
                    vehicle_id = cur.lastrowid
                else:
                    vehicle_id = vehicle["id"]

                cur.execute(
                    "SELECT id FROM parking_records WHERE vehicle_id = ? AND status = 'ativo'",
                    (vehicle_id,)
                )
                if cur.fetchone():
                    self.send_json({"error": "Veículo já está no estacionamento"}, 400)
                    return

                if spot_id:
                    cur.execute("SELECT id, status FROM spots WHERE id = ?", (spot_id,))
                    spot = cur.fetchone()
                    if not spot or spot["status"] != "livre":
                        self.send_json({"error": "Vaga indisponível"}, 400)
                        return
                else:
                    cur.execute("SELECT id FROM spots WHERE status = 'livre' ORDER BY type LIMIT 1")
                    spot = cur.fetchone()
                    if not spot:
                        self.send_json({"error": "Nenhuma vaga disponível"}, 400)
                        return
                    spot_id = spot["id"]

                now = datetime.now().isoformat()

                cur.execute(
                    """INSERT INTO parking_records (vehicle_id, spot_id, entry_time, status)
                       VALUES (?, ?, ?, 'ativo')""",
                    (vehicle_id, spot_id, now)
                )
                record_id = cur.lastrowid

                cur.execute(
                    "UPDATE spots SET status = 'ocupada', current_vehicle_id = ? WHERE id = ?",
                    (vehicle_id, spot_id)
                )

                conn.commit()
                self.send_json({
                    "id": record_id,
                    "message": "Entrada registrada",
                    "entry_time": now,
                    "spot_id": spot_id
                }, 201)

            elif path == "/api/exit":
                plate = data.get("plate", "").upper().replace(" ", "").replace("-", "")
                record_id = data.get("record_id")

                if record_id:
                    cur.execute(
                        """SELECT r.*, v.type as vehicle_type
                           FROM parking_records r
                           JOIN vehicles v ON r.vehicle_id = v.id
                           WHERE r.id = ? AND r.status = 'ativo'""",
                        (record_id,)
                    )
                elif plate:
                    cur.execute(
                        """SELECT r.*, v.type as vehicle_type
                           FROM parking_records r
                           JOIN vehicles v ON r.vehicle_id = v.id
                           WHERE v.plate = ? AND r.status = 'ativo'""",
                        (plate,)
                    )
                else:
                    self.send_json({"error": "Informe a placa"}, 400)
                    return

                record = cur.fetchone()
                if not record:
                    self.send_json({"error": "Registro ativo não encontrado"}, 404)
                    return

                now = datetime.now().isoformat()
                price = calculate_price(record["vehicle_type"], record["entry_time"], now)

                cur.execute(
                    """UPDATE parking_records
                       SET exit_time = ?, calculated_price = ?, status = 'finalizado'
                       WHERE id = ?""",
                    (now, price, record["id"])
                )

                cur.execute(
                    "UPDATE spots SET status = 'livre', current_vehicle_id = NULL WHERE id = ?",
                    (record["spot_id"],)
                )

                conn.commit()
                self.send_json({
                    "message": "Saída registrada",
                    "exit_time": now,
                    "price": price,
                    "duration_hours": round(
                        (datetime.fromisoformat(now) - datetime.fromisoformat(record["entry_time"])).total_seconds() / 3600, 2
                    )
                })

            elif path == "/api/tariffs":
                cur.execute(
                    """INSERT INTO tariffs (name, vehicle_type, period, price, description)
                       VALUES (?, ?, ?, ?, ?)""",
                    (data.get("name"), data.get("vehicle_type", "todos"), data.get("period"),
                     data.get("price"), data.get("description"))
                )
                conn.commit()
                self.send_json({"id": cur.lastrowid, "message": "Tarifa criada"}, 201)

            elif path == "/api/spots":
                cur.execute(
                    "INSERT INTO spots (number, type) VALUES (?, ?)",
                    (data.get("number"), data.get("type", "normal"))
                )
                conn.commit()
                self.send_json({"id": cur.lastrowid, "message": "Vaga criada"}, 201)

            else:
                self.send_json({"error": "Rota não encontrada"}, 404)

        except sqlite3.IntegrityError as e:
            self.send_json({"error": f"Erro de integridade: {str(e)}"}, 400)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)
        finally:
            conn.close()

    def handle_api_put(self, path, data):
        conn = get_connection()
        cur = conn.cursor()
        try:
            if path.startswith("/api/clients/"):
                client_id = int(path.split("/")[-1])
                cur.execute(
                    "UPDATE clients SET name=?, document=?, phone=?, email=? WHERE id=?",
                    (data.get("name"), data.get("document"), data.get("phone"), data.get("email"), client_id)
                )
                conn.commit()
                self.send_json({"message": "Cliente atualizado"})
            else:
                self.send_json({"error": "Rota não encontrada"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)
        finally:
            conn.close()

    def handle_api_delete(self, path):
        conn = get_connection()
        cur = conn.cursor()
        try:
            if path.startswith("/api/clients/"):
                client_id = int(path.split("/")[-1])
                cur.execute("DELETE FROM clients WHERE id = ?", (client_id,))
                conn.commit()
                self.send_json({"message": "Cliente removido"})
            elif path.startswith("/api/vehicles/"):
                vehicle_id = int(path.split("/")[-1])
                cur.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
                conn.commit()
                self.send_json({"message": "Veículo removido"})
            elif path.startswith("/api/spots/"):
                spot_id = int(path.split("/")[-1])
                cur.execute("SELECT status FROM spots WHERE id = ?", (spot_id,))
                spot = cur.fetchone()
                if spot and spot["status"] == "ocupada":
                    self.send_json({"error": "Não é possível remover vaga ocupada"}, 400)
                    return
                cur.execute("DELETE FROM spots WHERE id = ?", (spot_id,))
                conn.commit()
                self.send_json({"message": "Vaga removida"})
            else:
                self.send_json({"error": "Rota não encontrada"}, 404)
        except Exception as e:
            self.send_json({"error": str(e)}, 500)
        finally:
            conn.close()

def main():
    print("Inicializando banco de dados...")
    init_db()

    if not FRONTEND_DIR.exists():
        print(f"ERRO: Pasta frontend não encontrada em {FRONTEND_DIR}")
        input("Pressione Enter para sair...")
        return

    server = HTTPServer(("0.0.0.0", PORT), ParkingHandler)
    print(f"\nSistema de Estacionamento rodando!")
    print(f"   → http://localhost:{PORT}")
    print("\nPressione Ctrl+C para parar.\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
        server.server_close()

if __name__ == "__main__":
    main()