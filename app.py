from flask import Flask, render_template, request, jsonify, Response
import sqlite3
import csv
import io
import os

app = Flask(__name__)
DB_FILE = "agrivault.db"

def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def log_audit(cur, action, details):
    cur.execute("INSERT INTO audit_logs (action, details) VALUES (?, ?)", (action, details))

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # Unified Inventory/Silo Table
    cur.execute('''CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        item_name TEXT UNIQUE, 
        category TEXT, 
        current_amount REAL, 
        max_capacity REAL
    )''')
    
    cur.execute('''CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP, 
        action TEXT, 
        details TEXT
    )''')

    cur.execute("SELECT COUNT(*) FROM inventory")
    if cur.fetchone()[0] == 0:
        cur.executemany("INSERT INTO inventory (item_name, category, current_amount, max_capacity) VALUES (?, ?, ?, ?)", [
            ("Wheat", "Grain", 250, 1000), 
            ("Corn", "Grain", 300, 800), 
            ("Soy", "Legume", 150, 600)
        ])
        log_audit(cur, "SYSTEM_INIT", "Populated initial inventory and silos.")

    conn.commit()
    conn.close()

@app.route("/")
def index(): 
    return render_template("index.html")

@app.route("/api/inventory")
def get_inventory():
    return jsonify([dict(row) for row in get_conn().execute("SELECT * FROM inventory ORDER BY id").fetchall()])

@app.route("/api/logs")
def get_logs():
    return jsonify([dict(row) for row in get_conn().execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 15").fetchall()])

@app.route("/api/export")
def export_csv():
    conn = get_conn()
    items = conn.execute("SELECT id, item_name, category, current_amount, max_capacity FROM inventory ORDER BY id").fetchall()
    conn.close()

    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(["ID", "Crop/Item", "Category", "Current Stock (T)", "Max Capacity (T)"])
    for item in items:
        cw.writerow([item["id"], item["item_name"], item["category"], item["current_amount"], item["max_capacity"]])
    
    return Response(si.getvalue(), mimetype="text/csv", headers={"Content-Disposition": "attachment;filename=AgriVault_Report.csv"})

@app.route("/api/log_harvest", methods=["POST"])
def log_harvest():
    data = request.get_json()
    conn = get_conn()
    cur = conn.cursor()
    item = cur.execute("SELECT * FROM inventory WHERE id = ?", (data['silo_id'],)).fetchone()
    
    if item['current_amount'] + data['amount'] > item['max_capacity']:
        return jsonify({"error": "Capacity exceeded."}), 400

    new_amount = item["current_amount"] + data['amount']
    cur.execute("UPDATE inventory SET current_amount = ? WHERE id = ?", (new_amount, data['silo_id']))
    log_audit(cur, "HARVEST_LOG", f"Added {data['amount']}T to {item['item_name']}.")
    
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/inventory/<int:item_id>", methods=["PUT", "DELETE"])
def modify_inventory(item_id):
    conn = get_conn()
    cur = conn.cursor()
    item = cur.execute("SELECT * FROM inventory WHERE id=?", (item_id,)).fetchone()
    
    if request.method == "PUT":
        data = request.get_json()
        if data['quantity'] > item['max_capacity']:
            return jsonify({"error": "Cannot exceed max capacity."}), 400
        cur.execute("UPDATE inventory SET current_amount=? WHERE id=?", (data['quantity'], item_id))
        log_audit(cur, "STOCK_ADJUST", f"Manually updated {item['item_name']} stock to {data['quantity']}T.")
    elif request.method == "DELETE":
        cur.execute("DELETE FROM inventory WHERE id=?", (item_id,))
        log_audit(cur, "ITEM_PURGE", f"Deleted {item['item_name']} from database.")

    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/inventory/add", methods=["POST"])
def add_inventory():
    data = request.get_json()
    conn = get_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO inventory (item_name, category, current_amount, max_capacity) VALUES (?, ?, ?, ?)", 
                    (data['item_name'], data['category'], data['current_amount'], data['max_capacity']))
        log_audit(cur, "NEW_ITEM", f"Registered new catalog item: {data['item_name']}.")
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Item already exists."}), 400
    finally:
        conn.close()
    return jsonify({"success": True})

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
