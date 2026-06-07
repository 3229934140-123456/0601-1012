import sqlite3
import os
from datetime import datetime
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets.db")

ASSET_STATUS = ["闲置", "在用", "维修中", "已报废"]
ASSET_CATEGORIES = ["电脑", "工牌", "办公设备"]


def get_db_path():
    return os.path.abspath(DB_PATH)


@contextmanager
def get_db():
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS assets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_no TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                brand TEXT,
                model TEXT,
                serial_no TEXT,
                purchase_date TEXT,
                purchase_price REAL,
                department TEXT,
                location TEXT,
                user_name TEXT,
                status TEXT DEFAULT '闲置',
                depreciation_status TEXT DEFAULT '正常',
                remark TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                updated_at TEXT DEFAULT (datetime('now', 'localtime'))
            )
        ''')

        cursor.execute('''
            CREATE TABLE IF NOT EXISTS operation_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_no TEXT NOT NULL,
                operation TEXT NOT NULL,
                operator TEXT,
                detail TEXT,
                created_at TEXT DEFAULT (datetime('now', 'localtime')),
                FOREIGN KEY (asset_no) REFERENCES assets(asset_no)
            )
        ''')

        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_assets_asset_no ON assets(asset_no)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_assets_department ON assets(department)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_assets_status ON assets(status)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_asset_no ON operation_logs(asset_no)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_logs_operation ON operation_logs(operation)
        ''')


def log_operation(conn, asset_no, operation, operator=None, detail=None):
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO operation_logs (asset_no, operation, operator, detail)
        VALUES (?, ?, ?, ?)
    ''', (asset_no, operation, operator, detail))


def update_asset_timestamp(conn, asset_no):
    cursor = conn.cursor()
    cursor.execute('''
        UPDATE assets SET updated_at = datetime('now', 'localtime')
        WHERE asset_no = ?
    ''', (asset_no,))


def get_asset_by_no(conn, asset_no):
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM assets WHERE asset_no = ?', (asset_no,))
    return cursor.fetchone()


def asset_exists(conn, asset_no):
    return get_asset_by_no(conn, asset_no) is not None


def insert_asset(conn, asset_data):
    cursor = conn.cursor()
    columns = ', '.join(asset_data.keys())
    placeholders = ', '.join(['?' for _ in asset_data])
    cursor.execute(
        f'INSERT INTO assets ({columns}) VALUES ({placeholders})',
        list(asset_data.values())
    )
    return cursor.lastrowid


def update_asset(conn, asset_no, update_data):
    if not update_data:
        return
    set_clause = ', '.join([f'{k} = ?' for k in update_data.keys()])
    values = list(update_data.values()) + [asset_no]
    cursor = conn.cursor()
    cursor.execute(f'UPDATE assets SET {set_clause} WHERE asset_no = ?', values)


def query_assets(conn, filters=None, order_by='asset_no'):
    query = 'SELECT * FROM assets WHERE 1=1'
    params = []

    if filters:
        if filters.get('asset_no'):
            query += ' AND asset_no LIKE ?'
            params.append(f'%{filters["asset_no"]}%')
        if filters.get('name'):
            query += ' AND name LIKE ?'
            params.append(f'%{filters["name"]}%')
        if filters.get('category'):
            query += ' AND category = ?'
            params.append(filters['category'])
        if filters.get('department'):
            query += ' AND department = ?'
            params.append(filters['department'])
        if filters.get('status'):
            query += ' AND status = ?'
            params.append(filters['status'])
        if filters.get('user_name'):
            query += ' AND user_name LIKE ?'
            params.append(f'%{filters["user_name"]}%')
        if filters.get('location'):
            query += ' AND location LIKE ?'
            params.append(f'%{filters["location"]}%')
        if filters.get('date_from'):
            query += ' AND purchase_date >= ?'
            params.append(filters['date_from'])
        if filters.get('date_to'):
            query += ' AND purchase_date <= ?'
            params.append(filters['date_to'])

    query += f' ORDER BY {order_by}'

    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


def get_operation_logs(conn, filters=None):
    query = 'SELECT * FROM operation_logs WHERE 1=1'
    params = []

    if filters:
        if filters.get('asset_no'):
            query += ' AND asset_no LIKE ?'
            params.append(f'%{filters["asset_no"]}%')
        if filters.get('operation'):
            query += ' AND operation = ?'
            params.append(filters['operation'])
        if filters.get('date_from'):
            query += ' AND created_at >= ?'
            params.append(filters['date_from'])
        if filters.get('date_to'):
            query += ' AND created_at <= ?'
            params.append(filters['date_to'] + ' 23:59:59')

    query += ' ORDER BY created_at DESC'

    cursor = conn.cursor()
    cursor.execute(query, params)
    return cursor.fetchall()


def get_asset_statistics(conn):
    cursor = conn.cursor()
    stats = {}

    cursor.execute('SELECT category, COUNT(*) as count FROM assets GROUP BY category')
    stats['by_category'] = {row['category']: row['count'] for row in cursor.fetchall()}

    cursor.execute('SELECT status, COUNT(*) as count FROM assets GROUP BY status')
    stats['by_status'] = {row['status']: row['count'] for row in cursor.fetchall()}

    cursor.execute('SELECT department, COUNT(*) as count FROM assets GROUP BY department')
    stats['by_department'] = {row['department']: row['count'] for row in cursor.fetchall()}

    cursor.execute('SELECT COUNT(*) as total FROM assets')
    stats['total'] = cursor.fetchone()['total']

    cursor.execute('SELECT SUM(purchase_price) as total_value FROM assets')
    stats['total_value'] = cursor.fetchone()['total_value'] or 0

    return stats
