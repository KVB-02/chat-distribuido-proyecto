import sqlite3
from pathlib import Path
from werkzeug.security import generate_password_hash, check_password_hash

# La base de datos se guardará en la carpeta principal del proyecto.
DB_PATH = Path(__file__).resolve().parent / "chat.db"

# Segundos máximos desde la última petición para considerar activo a un usuario.
ACTIVE_WINDOW_SECONDS = 15


def get_connection():
    """Crea una conexión con la base de datos."""
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Crea las tablas necesarias para el chat distribuido y aplica migraciones seguras."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                is_online INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT
            );

            CREATE TABLE IF NOT EXISTS rooms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE COLLATE NOCASE,
                created_by INTEGER,
                created_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                is_group INTEGER NOT NULL DEFAULT 1,
                is_private INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY (created_by) REFERENCES users(id)
                    ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS room_members (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL DEFAULT 'member',
                joined_at TEXT NOT NULL DEFAULT
                    (strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')),
                PRIMARY KEY (room_id, user_id),
                FOREIGN KEY (room_id) REFERENCES rooms(id)
                    ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id)
                    ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS room_left_users (
                room_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                left_at TEXT NOT NULL DEFAULT
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

        # Migraciones seguras para la tabla users
        user_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "is_online" not in user_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN is_online INTEGER NOT NULL DEFAULT 0"
            )
        if "last_seen" not in user_columns:
            conn.execute(
                "ALTER TABLE users ADD COLUMN last_seen TEXT"
            )

        # Migraciones seguras para la tabla rooms
        room_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(rooms)").fetchall()
        }
        if "is_group" not in room_columns:
            conn.execute(
                "ALTER TABLE rooms ADD COLUMN is_group INTEGER NOT NULL DEFAULT 1"
            )
        if "is_private" not in room_columns:
            conn.execute(
                "ALTER TABLE rooms ADD COLUMN is_private INTEGER NOT NULL DEFAULT 0"
            )

        # Migraciones seguras para la tabla room_members
        member_columns = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(room_members)").fetchall()
        }
        if "role" not in member_columns:
            conn.execute(
                "ALTER TABLE room_members ADD COLUMN role TEXT NOT NULL DEFAULT 'member'"
            )

        # Asegurar que el creador de cada sala existente tenga rol de administrador
        conn.execute("""
            UPDATE room_members
            SET role = 'admin'
            WHERE (room_id, user_id) IN (
                SELECT id, created_by FROM rooms WHERE created_by IS NOT NULL
            )
        """)

        # Crear una sala inicial para facilitar la primera prueba.
        conn.execute(
            "INSERT OR IGNORE INTO rooms (name, is_group, is_private) VALUES (?, 1, 0)",
            ("General",)
        )


def update_user_presence(username, is_online=True):
    """Actualiza el estado de conexión y la marca de actividad del usuario."""
    if not username:
        return False
    with get_connection() as conn:
        if is_online:
            conn.execute(
                """
                UPDATE users
                SET is_online = 1,
                    last_seen = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
                WHERE username = ?
                """,
                (username.strip(),)
            )
        else:
            conn.execute(
                """
                UPDATE users
                SET is_online = 0
                WHERE username = ?
                """,
                (username.strip(),)
            )
    return True


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
        update_user_presence(user["username"], is_online=True)
        return {
            "id": user["id"],
            "username": user["username"]
        }
    return None


def search_users(query, exclude_username=None, limit=15):
    """Busca usuarios registrados por coincidencia parcial o exacta en su username."""
    clean_query = (query or "").strip()
    if not clean_query:
        return []

    limit = max(1, min(int(limit), 50))
    pattern = f"%{clean_query}%"

    with get_connection() as conn:
        if exclude_username:
            rows = conn.execute(
                """
                SELECT
                    id,
                    username,
                    CASE
                        WHEN is_online = 1
                         AND last_seen IS NOT NULL
                         AND (
                             strftime('%s', 'now', 'localtime') -
                             strftime('%s', last_seen)
                         ) <= ?
                        THEN 1
                        ELSE 0
                    END AS is_active
                FROM users
                WHERE username LIKE ? COLLATE NOCASE
                  AND username != ? COLLATE NOCASE
                ORDER BY
                    CASE WHEN username = ? COLLATE NOCASE THEN 0 ELSE 1 END,
                    username COLLATE NOCASE ASC
                LIMIT ?
                """,
                (ACTIVE_WINDOW_SECONDS, pattern, exclude_username.strip(), clean_query, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    id,
                    username,
                    CASE
                        WHEN is_online = 1
                         AND last_seen IS NOT NULL
                         AND (
                             strftime('%s', 'now', 'localtime') -
                             strftime('%s', last_seen)
                         ) <= ?
                        THEN 1
                        ELSE 0
                    END AS is_active
                FROM users
                WHERE username LIKE ? COLLATE NOCASE
                ORDER BY username COLLATE NOCASE ASC
                LIMIT ?
                """,
                (ACTIVE_WINDOW_SECONDS, pattern, limit)
            ).fetchall()

    return [
        {
            "id": row["id"],
            "username": row["username"],
            "is_active": bool(row["is_active"])
        }
        for row in rows
    ]


def create_group_with_members(group_name, creator_username, participant_usernames):
    """
    Crea un grupo nuevo asignando al creador como miembro y administrador inicial,
    y agregando únicamente a los usuarios seleccionados.
    """
    if not isinstance(group_name, str) or not group_name.strip():
        return None, "El nombre del grupo es obligatorio y no puede contener solo espacios."

    clean_name = group_name.strip()
    if len(clean_name) > 50:
        return None, "El nombre del grupo debe tener entre 1 y 50 caracteres."

    if not creator_username or not str(creator_username).strip():
        return None, "El usuario creador no es válido."

    creator_username = creator_username.strip()

    if not isinstance(participant_usernames, (list, tuple)):
        return None, "Formato de participantes inválido."

    # Normalizar y eliminar duplicados preservando el orden
    normalized_participants = []
    seen_lower = {creator_username.lower()}
    for raw_user in participant_usernames:
        if not isinstance(raw_user, str):
            continue
        candidate = raw_user.strip()
        if not candidate:
            continue
        low = candidate.lower()
        if low in seen_lower:
            continue
        seen_lower.add(low)
        normalized_participants.append(candidate)

    if len(normalized_participants) == 0:
        return (
            None,
            "Debes seleccionar al menos otro participante para crear un grupo."
        )

    with get_connection() as conn:
        creator = conn.execute(
            "SELECT id, username FROM users WHERE username = ?",
            (creator_username,)
        ).fetchone()
        if not creator:
            return None, "El usuario creador no existe."

        existing_room = conn.execute(
            "SELECT id FROM rooms WHERE name = ?",
            (clean_name,)
        ).fetchone()
        if existing_room:
            return None, f"Ya existe un grupo o sala con el nombre «{clean_name}»."

        # Verificar que todos los participantes seleccionados existan en el sistema
        resolved_users = []
        missing_users = []
        for uname in normalized_participants:
            user_row = conn.execute(
                "SELECT id, username FROM users WHERE username = ?",
                (uname,)
            ).fetchone()
            if not user_row:
                missing_users.append(uname)
            else:
                resolved_users.append(user_row)

        if missing_users:
            missing_str = ", ".join(missing_users)
            return None, f"El usuario «{missing_str}» no existe en el sistema."

        # Actualizar presencia del creador
        conn.execute(
            """
            UPDATE users
            SET is_online = 1,
                last_seen = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
            WHERE id = ?
            """,
            (creator["id"],)
        )

        # Crear el grupo privado (solo accesible para los miembros seleccionados)
        cursor = conn.execute(
            """
            INSERT INTO rooms (name, created_by, is_group, is_private)
            VALUES (?, ?, 1, 1)
            """,
            (clean_name, creator["id"])
        )
        room_id = cursor.lastrowid

        # Insertar al creador como miembro y administrador inicial
        conn.execute(
            """
            INSERT INTO room_members (room_id, user_id, role)
            VALUES (?, ?, 'admin')
            """,
            (room_id, creator["id"])
        )
        conn.execute(
            "DELETE FROM room_left_users WHERE room_id = ? AND user_id = ?",
            (room_id, creator["id"])
        )

        # Insertar únicamente a los participantes seleccionados como miembros
        for participant in resolved_users:
            conn.execute(
                """
                INSERT OR IGNORE INTO room_members (room_id, user_id, role)
                VALUES (?, ?, 'member')
                """,
                (room_id, participant["id"])
            )
            conn.execute(
                "DELETE FROM room_left_users WHERE room_id = ? AND user_id = ?",
                (room_id, participant["id"])
            )

        return {
            "id": room_id,
            "name": clean_name,
            "is_group": True,
            "is_private": True,
            "role": "admin"
        }, None


def get_or_create_room(room_name, username):
    """Obtiene una sala pública o la crea y añade al usuario como miembro si tiene permiso."""
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
            """
            UPDATE users
            SET is_online = 1,
                last_seen = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
            WHERE id = ?
            """,
            (user["id"],)
        )

        room = conn.execute(
            "SELECT id, name, is_group, is_private FROM rooms WHERE name = ?",
            (room_name,)
        ).fetchone()

        if room is None:
            cursor = conn.execute(
                """
                INSERT INTO rooms (name, created_by, is_group, is_private)
                VALUES (?, ?, 1, 0)
                """,
                (room_name, user["id"])
            )
            room_id = cursor.lastrowid
            conn.execute(
                """
                INSERT INTO room_members (room_id, user_id, role)
                VALUES (?, ?, 'admin')
                """,
                (room_id, user["id"])
            )
            conn.execute(
                "DELETE FROM room_left_users WHERE room_id = ? AND user_id = ?",
                (room_id, user["id"])
            )
            return {
                "id": room_id,
                "name": room_name,
                "is_group": True,
                "is_private": False
            }, None

        # Si la sala ya existe, comprobar si es miembro
        membership = conn.execute(
            """
            SELECT role FROM room_members
            WHERE room_id = ? AND user_id = ?
            """,
            (room["id"], user["id"])
        ).fetchone()

        if membership:
            return {
                "id": room["id"],
                "name": room["name"],
                "is_group": bool(room["is_group"]),
                "is_private": bool(room["is_private"])
            }, None

        # Verificar si el usuario abandonó previamente este grupo
        has_left = conn.execute(
            """
            SELECT 1 FROM room_left_users
            WHERE room_id = ? AND user_id = ?
            """,
            (room["id"], user["id"])
        ).fetchone()
        if has_left:
            return None, "Abandonaste este grupo y ya no tienes acceso a él."

        # Si el grupo es privado y el usuario no fue invitado, denegar acceso
        if room["is_private"]:
            return None, "No perteneces a este grupo privado."

        # Sala pública abierta de la que el usuario no ha salido
        conn.execute(
            """
            INSERT OR IGNORE INTO room_members (room_id, user_id, role)
            VALUES (?, ?, 'member')
            """,
            (room["id"], user["id"])
        )
        return {
            "id": room["id"],
            "name": room["name"],
            "is_group": bool(room["is_group"]),
            "is_private": bool(room["is_private"])
        }, None


def join_existing_room(room_id, username):
    """Permite abrir una conversación verificando permisos de pertenencia."""
    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username,)
        ).fetchone()
        if not user:
            return None, "El usuario no existe.", 404

        room = conn.execute(
            "SELECT id, name, is_group, is_private FROM rooms WHERE id = ?",
            (room_id,)
        ).fetchone()
        if not room:
            return None, "El grupo o sala no existe.", 404

        membership = conn.execute(
            """
            SELECT role FROM room_members
            WHERE room_id = ? AND user_id = ?
            """,
            (room_id, user["id"])
        ).fetchone()

        if membership:
            return {
                "id": room["id"],
                "name": room["name"],
                "is_group": bool(room["is_group"]),
                "is_private": bool(room["is_private"]),
                "role": membership["role"]
            }, None, 200

        # Si no es miembro, verificar si salió del grupo o si el grupo es privado
        has_left = conn.execute(
            """
            SELECT 1 FROM room_left_users
            WHERE room_id = ? AND user_id = ?
            """,
            (room_id, user["id"])
        ).fetchone()
        if has_left:
            return None, "Has salido de este grupo y no puedes acceder a él.", 403

        if room["is_private"]:
            return None, "No perteneces a este grupo.", 403

        # Si es una sala general pública y no ha salido de ella, registrar su entrada
        conn.execute(
            """
            INSERT OR IGNORE INTO room_members (room_id, user_id, role)
            VALUES (?, ?, 'member')
            """,
            (room_id, user["id"])
        )
        return {
            "id": room["id"],
            "name": room["name"],
            "is_group": bool(room["is_group"]),
            "is_private": bool(room["is_private"]),
            "role": "member"
        }, None, 200


def list_rooms(username=None):
    """
    Devuelve las salas y grupos visibles para el usuario conectado.
    - Si se indica username: incluye los grupos donde es miembro activo y las salas públicas
      de las que no haya salido. Excluye grupos privados ajenos y grupos abandonados.
    """
    with get_connection() as conn:
        if not username:
            rows = conn.execute(
                """
                SELECT id, name, is_group, is_private
                FROM rooms
                ORDER BY name COLLATE NOCASE ASC
                """
            ).fetchall()
            return [
                {
                    "id": row["id"],
                    "name": row["name"],
                    "is_group": bool(row["is_group"]),
                    "is_private": bool(row["is_private"]),
                    "is_member": True,
                    "role": "member"
                }
                for row in rows
            ]

        user = conn.execute(
            "SELECT id FROM users WHERE username = ?",
            (username.strip(),)
        ).fetchone()
        if not user:
            return []

        rows = conn.execute(
            """
            SELECT
                r.id,
                r.name,
                r.is_group,
                r.is_private,
                rm.role AS member_role,
                CASE WHEN rm.user_id IS NOT NULL THEN 1 ELSE 0 END AS is_member
            FROM rooms r
            LEFT JOIN room_members rm
                ON rm.room_id = r.id AND rm.user_id = ?
            LEFT JOIN room_left_users rlu
                ON rlu.room_id = r.id AND rlu.user_id = ?
            WHERE rm.user_id IS NOT NULL
               OR (r.is_private = 0 AND rlu.user_id IS NULL)
            ORDER BY r.name COLLATE NOCASE ASC
            """,
            (user["id"], user["id"])
        ).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "is_group": bool(row["is_group"]),
            "is_private": bool(row["is_private"]),
            "is_member": bool(row["is_member"]),
            "role": row["member_role"] or "member"
        }
        for row in rows
    ]


def leave_group(room_id, username):
    """
    Elimina la pertenencia de un usuario a un grupo, gestionando la transferencia
    de administrador si corresponde y conservando el grupo y sus mensajes.
    """
    if not username:
        return None, "Usuario no autenticado."

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id, username FROM users WHERE username = ?",
            (username.strip(),)
        ).fetchone()
        if not user:
            return None, "El usuario no existe."

        room = conn.execute(
            "SELECT id, name, created_by, is_group, is_private FROM rooms WHERE id = ?",
            (room_id,)
        ).fetchone()
        if not room:
            return None, "El grupo no existe."

        if not room["is_group"]:
            return None, "Esta acción solo está disponible en grupos, no en chats individuales."

        membership = conn.execute(
            """
            SELECT role FROM room_members
            WHERE room_id = ? AND user_id = ?
            """,
            (room_id, user["id"])
        ).fetchone()

        if not membership:
            return None, "No perteneces a este grupo."

        was_admin = (membership["role"] == "admin") or (room["created_by"] == user["id"])

        # Eliminar la pertenencia del usuario que sale (sin alterar la de otros usuarios)
        conn.execute(
            "DELETE FROM room_members WHERE room_id = ? AND user_id = ?",
            (room_id, user["id"])
        )

        # Registrar que el usuario abandonó voluntariamente el grupo
        conn.execute(
            """
            INSERT OR REPLACE INTO room_left_users (room_id, user_id, left_at)
            VALUES (?, ?, strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime'))
            """,
            (room_id, user["id"])
        )

        # Consultar los miembros restantes ordenados por antigüedad
        remaining_members = conn.execute(
            """
            SELECT rm.user_id, rm.role, u.username
            FROM room_members rm
            JOIN users u ON u.id = rm.user_id
            WHERE rm.room_id = ?
            ORDER BY rm.joined_at ASC, rm.user_id ASC
            """,
            (room_id,)
        ).fetchall()

        new_admin_username = None

        if len(remaining_members) > 0:
            remaining_admins = [
                m for m in remaining_members if m["role"] == "admin"
            ]
            if len(remaining_admins) == 0:
                # Transferir el rol de administrador al miembro más antiguo
                promoted = remaining_members[0]
                conn.execute(
                    """
                    UPDATE room_members
                    SET role = 'admin'
                    WHERE room_id = ? AND user_id = ?
                    """,
                    (room_id, promoted["user_id"])
                )
                conn.execute(
                    "UPDATE rooms SET created_by = ? WHERE id = ?",
                    (promoted["user_id"], room_id)
                )
                new_admin_username = promoted["username"]
            elif room["created_by"] == user["id"]:
                # Si había otros administradores, actualizar created_by a uno de ellos
                conn.execute(
                    "UPDATE rooms SET created_by = ? WHERE id = ?",
                    (remaining_admins[0]["user_id"], room_id)
                )
        else:
            # Si era el único integrante, se conserva el grupo y sus mensajes sin borrarlos
            if was_admin:
                conn.execute(
                    "UPDATE rooms SET created_by = NULL WHERE id = ?",
                    (room_id,)
                )

        # Notificación en tiempo real mediante mensaje de sistema para los miembros restantes
        if new_admin_username:
            system_text = (
                f"ℹ️ {user['username']} ha salido del grupo. "
                f"{new_admin_username} es ahora administrador del grupo."
            )
        else:
            system_text = f"ℹ️ {user['username']} ha salido del grupo."

        conn.execute(
            """
            INSERT INTO messages (room_id, user_id, username, content)
            VALUES (?, NULL, 'Sistema', ?)
            """,
            (room_id, system_text)
        )

        return {
            "room_id": room["id"],
            "room_name": room["name"],
            "new_admin": new_admin_username,
            "remaining_count": len(remaining_members)
        }, None


def user_is_member(room_id, username):
    """Comprueba que el usuario pertenece actualmente a la sala o grupo."""
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


def get_room_members(room_id, username):
    """Devuelve los usuarios que pertenecen a una sala, su rol y su estado de conexión."""
    if not user_is_member(room_id, username):
        return None, "No perteneces a este grupo o sala."

    update_user_presence(username, is_online=True)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT
                u.id,
                u.username,
                COALESCE(rm.role, 'member') AS role,
                COALESCE(u.last_seen, '') AS last_seen,
                CASE
                    WHEN u.is_online = 1
                     AND u.last_seen IS NOT NULL
                     AND (
                         strftime('%s', 'now', 'localtime') -
                         strftime('%s', u.last_seen)
                     ) <= ?
                    THEN 1
                    ELSE 0
                END AS is_active
            FROM room_members rm
            JOIN users u ON u.id = rm.user_id
            WHERE rm.room_id = ?
            ORDER BY
                is_active DESC,
                CASE WHEN rm.role = 'admin' THEN 0 ELSE 1 END ASC,
                u.username COLLATE NOCASE ASC
            """,
            (ACTIVE_WINDOW_SECONDS, room_id)
        ).fetchall()

    members = [
        {
            "user_id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "is_active": bool(row["is_active"]),
            "last_seen": row["last_seen"]
        }
        for row in rows
    ]
    return members, None


def save_message(room_id, username, content):
    """Guarda un mensaje enviado a una sala verificando estrictamente la membresía."""
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
            return None, "No perteneces a este grupo y no puedes enviar mensajes."

        conn.execute(
            """
            UPDATE users
            SET is_online = 1,
                last_seen = strftime('%Y-%m-%d %H:%M:%S', 'now', 'localtime')
            WHERE id = ?
            """,
            (user["id"],)
        )

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
    """Consulta el historial de mensajes de una sala verificando pertenencia."""
    if not user_is_member(room_id, username):
        return None, "No perteneces a este grupo o sala."

    update_user_presence(username, is_online=True)
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