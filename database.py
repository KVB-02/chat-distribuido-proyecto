import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

# La base de datos se guardará en la carpeta principal del proyecto.
DB_PATH = Path(__file__).resolve().parent / "chat.db"


def get_connection():
    """Crea una conexión con la base de datos."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crea las tablas necesarias para el chat distribuido."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                FOREIGN KEY (created_by) REFERENCES users(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                PRIMARY KEY (room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES rooms(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room_id INTEGER NOT NULL,
                user_id INTEGER,
                username TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                FOREIGN KEY (room_id) REFERENCES rooms(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE SET NULL
            );

            CREATE INDEX IF NOT EXISTS idx_messages_room
            ON messages(room_id, id);

            CREATE INDEX IF NOT EXISTS idx_room_members_user
            ON room_members(user_id);
        """)

        # Crear una sala inicial para facilitar la primera prueba.
        conn.execute(
            "INSERT OR IGNORE INTO rooms (name) VALUES (?)",
            ("General",)
        )


def register_user(username, password):
    """Registra un usuario almacenando el hash de su contraseña."""
    username = username.strip()

    if len(username) < 3 or len(username) > 30:
        return False, "El usuario debe tener entre 3 y 30 caracteres."

    if not username.replace("_", "").isalnum():
        return False, "Usa solo letras, números y guion bajo en el usuario."

    if len(password) < 8:
        return False, "La contraseña debe tener al menos 8 caracteres."

    password_hash = generate_password_hash(password)

    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO users (username, password_hash) VALUES (?, ?)",
                (username, password_hash)
            )
        return True, "Usuario registrado correctamente."

    except sqlite3.IntegrityError:
        return False, "Ese nombre de usuario ya está registrado."


def authenticate_user(username, password):
    """Comprueba las credenciales sin almacenar la contraseña original."""
    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT id, username, password_hash
            FROM users
            WHERE username = ?
            """,
            (username.strip(),)
        ).fetchone()

    if user and check_password_hash(user["password_hash"], password):
        return {
            "id": user["id"],
            "username": user["username"]
        }

    return None


def get_or_create_room(room_name, username):
    """Obtiene una sala o la crea y añade al usuario como miembro."""
    room_name = room_name.strip()

    if not room_name or len(room_name) > 50:
        return None, "El nombre de la sala debe tener entre 1 y 50 caracteres."

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if not user:
            return None, "El usuario no existe."

        conn.execute(
            "INSERT OR IGNORE INTO rooms (name, created_by) VALUES (?, ?)",
            (room_name, user["id"])
        )

        room = conn.execute(
            "SELECT id, name FROM rooms WHERE name = ?",
            (room_name,)
        ).fetchone()

        conn.execute(
            """
            INSERT OR IGNORE INTO room_members (room_id, user_id)
            VALUES (?, ?)
            """,
            (room["id"], user["id"])
        )

        return {"id": room["id"], "name": room["name"]}, None


def list_rooms():
    """Devuelve las salas registradas."""
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT id, name FROM rooms ORDER BY name"
        ).fetchall()

    return [dict(row) for row in rows]


def user_is_member(room_id, username):
    """Comprueba que el usuario pertenece a la sala."""
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT 1
            FROM room_members rm
            JOIN users u ON u.id = rm.user_id
            WHERE rm.room_id = ? AND u.username = ?
            """,
            (room_id, username)
        ).fetchone()

    return row is not None


def save_message(room_id, username, content):
    """Guarda un mensaje enviado a una sala."""
    content = content.strip()

    if not content or len(content) > 2000:
        return None, "El mensaje debe tener entre 1 y 2000 caracteres."

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()

        if not user:
            return None, "El usuario no existe."

        member = conn.execute(
            """
            SELECT 1 FROM room_members
            WHERE room_id = ? AND user_id = ?
            """,
            (room_id, user["id"])
        ).fetchone()

        if not member:
            return None, "Debes entrar en la sala antes de enviar mensajes."

        cursor = conn.execute(
            """
            INSERT INTO messages (room_id, user_id, username, content)
            VALUES (?, ?, ?, ?)
            """,
            (room_id, user["id"], username, content)
        )

        message_id = cursor.lastrowid

        row = conn.execute(
            "SELECT created_at FROM messages WHERE id = ?",
            (message_id,)
        ).fetchone()

        return {
            "id": message_id,
            "room_id": room_id,
            "username": username,
            "content": content,
            "timestamp": row["created_at"]
        }, None


def get_messages(room_id, username, limit=100):
    """Consulta el historial de mensajes de una sala."""
    if not user_is_member(room_id, username):
        return None, "No perteneces a esta sala."

    limit = max(1, min(int(limit), 200))

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, room_id, username, content, created_at
            FROM messages
            WHERE room_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (room_id, limit)
        ).fetchall()

    messages = [
        {
            "id": row["id"],
            "room_id": row["room_id"],
            "username": row["username"],
            "content": row["content"],
            "timestamp": row["created_at"]
        }
        for row in reversed(rows)
    ]

    return messages, None