import os
from functools import wraps
import grpc
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    session,
    flash,
    jsonify
)
import chat_pb2
import chat_pb2_grpc
import database

app = Flask(__name__)
# Cambiar por una clave secreta propia antes de usarlo fuera de pruebas.
app.secret_key = os.environ.get(
    "FLASK_SECRET_KEY",
    "clave-temporal-solo-para-desarrollo"
)

GRPC_HOST = os.environ.get("GRPC_HOST", "127.0.0.1")
GRPC_PORT = int(os.environ.get("GRPC_PORT", "50051"))
GRPC_ADDRESS = f"{GRPC_HOST}:{GRPC_PORT}"


def get_grpc_stub():
    """Crea un cliente para comunicarse con el servidor gRPC."""
    channel = grpc.insecure_channel(GRPC_ADDRESS)
    stub = chat_pb2_grpc.ChatServiceStub(channel)
    return channel, stub


def login_required(view):
    """Restringe el acceso a usuarios que iniciaron sesión."""
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "username" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Debes iniciar sesión para continuar."}), 401
            flash("Debes iniciar sesión para continuar.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped_view


@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("chat"))
    return redirect(url_for("login"))


@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if password != confirm_password:
            flash("Las contraseñas no coinciden.", "error")
            return render_template("registro.html")

        success, message = database.register_user(username, password)
        if success:
            flash("Registro completado. Ahora inicia sesión.", "success")
            return redirect(url_for("login"))
        flash(message, "error")

    return render_template("registro.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = database.authenticate_user(username, password)
        if user:
            session.clear()
            session["username"] = user["username"]
            session["user_id"] = user["id"]
            flash("Bienvenido al chat distribuido.", "success")
            return redirect(url_for("chat"))

        flash("Usuario o contraseña incorrectos.", "error")

    return render_template("login.html")


@app.route("/logout", methods=["POST"])
def logout():
    username = session.get("username")
    if username:
        channel = None
        try:
            channel, stub = get_grpc_stub()
            if hasattr(stub, "UpdatePresence") and hasattr(chat_pb2, "PresenceRequest"):
                stub.UpdatePresence(
                    chat_pb2.PresenceRequest(username=username, is_online=False),
                    timeout=2
                )
            else:
                database.update_user_presence(username, is_online=False)
        except grpc.RpcError:
            database.update_user_presence(username, is_online=False)
        finally:
            if channel:
                channel.close()

    session.clear()
    flash("Has cerrado sesión.", "success")
    return redirect(url_for("login"))


@app.route("/chat")
@login_required
def chat():
    database.update_user_presence(session["username"], is_online=True)
    return render_template(
        "chat.html",
        username=session["username"]
    )


@app.route("/api/users/search", methods=["GET"])
@login_required
def api_search_users():
    query = request.args.get("q", "").strip()
    if not query:
        return jsonify({"users": []})

    channel = None
    try:
        channel, stub = get_grpc_stub()
        if hasattr(stub, "SearchUsers") and hasattr(chat_pb2, "SearchUsersRequest"):
            response = stub.SearchUsers(
                chat_pb2.SearchUsersRequest(
                    query=query,
                    exclude_username=session["username"]
                ),
                timeout=3
            )
            users = [
                {
                    "id": u.user_id,
                    "username": u.username,
                    "is_active": u.is_active
                }
                for u in response.users
            ]
        else:
            stub.ListRooms(chat_pb2.Empty(), timeout=3)
            users = database.search_users(
                query,
                exclude_username=session["username"]
            )
        return jsonify({"users": users})
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms", methods=["GET"])
@login_required
def api_list_rooms():
    channel = None
    try:
        database.update_user_presence(session["username"], is_online=True)
        channel, stub = get_grpc_stub()
        # Verificar conexión activa con el servidor gRPC
        stub.ListRooms(chat_pb2.Empty(), timeout=3)
        rooms = database.list_rooms(session["username"])
        return jsonify({"rooms": rooms})
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms", methods=["POST"])
@login_required
def api_create_room():
    data = request.get_json(silent=True) or {}
    room_name = (data.get("name") or "").strip()
    if not room_name:
        return jsonify({"error": "Escribe el nombre de la sala."}), 400

    channel = None
    try:
        channel, stub = get_grpc_stub()
        response = stub.CreateRoom(
            chat_pb2.RoomRequest(
                room_name=room_name,
                username=session["username"]
            ),
            timeout=3
        )
        if not response.success:
            return jsonify({"error": response.message}), 400

        return jsonify({
            "id": response.room_id,
            "name": room_name,
            "is_group": True,
            "is_private": False,
            "message": response.message
        }), 201
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/groups", methods=["POST"])
@login_required
def api_create_group():
    data = request.get_json(silent=True) or {}
    raw_name = data.get("name", "")
    participants = data.get("participants", [])

    if not isinstance(raw_name, str) or not raw_name.strip():
        return jsonify({
            "error": "El nombre del grupo es obligatorio y no puede contener solo espacios."
        }), 400

    if not isinstance(participants, list):
        return jsonify({
            "error": "La lista de participantes no es válida."
        }), 400

    group_name = raw_name.strip()

    channel = None
    try:
        channel, stub = get_grpc_stub()
        if hasattr(stub, "CreateGroup") and hasattr(chat_pb2, "CreateGroupRequest"):
            response = stub.CreateGroup(
                chat_pb2.CreateGroupRequest(
                    group_name=group_name,
                    creator_username=session["username"],
                    participants=[str(p) for p in participants if isinstance(p, str)]
                ),
                timeout=3
            )
            if not response.success:
                return jsonify({"error": response.message}), 400
            return jsonify({
                "id": response.room_id,
                "name": group_name,
                "is_group": True,
                "is_private": True,
                "message": response.message
            }), 201
        else:
            stub.ListRooms(chat_pb2.Empty(), timeout=3)
            group, error = database.create_group_with_members(
                group_name,
                session["username"],
                participants
            )
            if error:
                return jsonify({"error": error}), 400
            return jsonify({
                "id": group["id"],
                "name": group["name"],
                "is_group": True,
                "is_private": True,
                "message": "Grupo creado correctamente."
            }), 201
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms/<int:room_id>/join", methods=["POST"])
@login_required
def api_join_room(room_id):
    channel = None
    try:
        channel, stub = get_grpc_stub()
        stub.ListRooms(chat_pb2.Empty(), timeout=3)
        room, error, status_code = database.join_existing_room(
            room_id,
            session["username"]
        )
        if error:
            return jsonify({"error": error}), status_code

        return jsonify({
            "id": room["id"],
            "name": room["name"],
            "is_group": room["is_group"],
            "is_private": room["is_private"],
            "role": room["role"],
            "message": "Has entrado en la sala."
        })
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms/<int:room_id>/leave", methods=["POST"])
@login_required
def api_leave_room(room_id):
    channel = None
    try:
        channel, stub = get_grpc_stub()
        if hasattr(stub, "LeaveRoom") and hasattr(chat_pb2, "LeaveRoomRequest"):
            response = stub.LeaveRoom(
                chat_pb2.LeaveRoomRequest(
                    room_id=room_id,
                    username=session["username"]
                ),
                timeout=3
            )
            if not response.success:
                return jsonify({"error": response.message}), 400
            return jsonify({
                "message": response.message,
                "new_admin": response.new_admin
            })
        else:
            stub.ListRooms(chat_pb2.Empty(), timeout=3)
            result, error = database.leave_group(room_id, session["username"])
            if error:
                return jsonify({"error": error}), 400
            return jsonify({
                "message": f"Has salido del grupo «{result['room_name']}».",
                "new_admin": result.get("new_admin") or ""
            })
    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms/<int:room_id>/members", methods=["GET"])
@login_required
def api_get_room_members(room_id):
    channel = None
    try:
        channel, stub = get_grpc_stub()
        stub.ListRooms(chat_pb2.Empty(), timeout=3)
        members_data, error = database.get_room_members(
            room_id,
            session["username"]
        )
        if error:
            return jsonify({"error": error}), 403

        online_count = sum(1 for m in members_data if m["is_active"])
        offline_count = len(members_data) - online_count

        return jsonify({
            "members": members_data,
            "online_count": online_count,
            "offline_count": offline_count,
            "total_count": len(members_data)
        })
    except grpc.RpcError as error:
        if error.code() == grpc.StatusCode.PERMISSION_DENIED:
            return jsonify({
                "error": "Debes pertenecer al grupo para ver sus miembros."
            }), 403
        if error.code() == grpc.StatusCode.UNAVAILABLE:
            return jsonify({
                "error": "El servidor gRPC no está disponible."
            }), 503
        return jsonify({
            "error": "No fue posible consultar los miembros de la sala."
        }), 500
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms/<int:room_id>/messages", methods=["GET"])
@login_required
def api_get_messages(room_id):
    channel = None
    try:
        channel, stub = get_grpc_stub()
        response = stub.GetMessages(
            chat_pb2.HistoryRequest(
                room_id=room_id,
                limit=100,
                username=session["username"]
            ),
            timeout=3
        )
        messages = [
            {
                "id": message.message_id,
                "room_id": message.room_id,
                "username": message.username,
                "content": message.content,
                "timestamp": message.timestamp
            }
            for message in response.messages
        ]
        return jsonify({"messages": messages})
    except grpc.RpcError as error:
        if error.code() == grpc.StatusCode.PERMISSION_DENIED:
            return jsonify({
                "error": "No perteneces a este grupo para consultar sus mensajes."
            }), 403
        if error.code() == grpc.StatusCode.UNAVAILABLE:
            return jsonify({
                "error": "El servidor gRPC no está disponible."
            }), 503
        return jsonify({
            "error": "No fue posible consultar los mensajes."
        }), 500
    finally:
        if channel:
            channel.close()


@app.route("/api/rooms/<int:room_id>/messages", methods=["POST"])
@login_required
def api_send_message(room_id):
    data = request.get_json(silent=True) or {}
    content = data.get("content", "")

    if not isinstance(content, str) or not content.strip():
        return jsonify({"error": "El mensaje no puede estar vacío."}), 400
    if len(content) > 2000:
        return jsonify({"error": "El mensaje supera los 2000 caracteres."}), 400

    channel = None
    try:
        channel, stub = get_grpc_stub()
        response = stub.SendMessage(
            chat_pb2.MessageRequest(
                room_id=room_id,
                username=session["username"],
                content=content
            ),
            timeout=3
        )
        if not response.success:
            status_code = 403 if "perteneces" in response.message.lower() or "entrar" in response.message.lower() else 400
            return jsonify({"error": response.message}), status_code

        return jsonify({
            "id": response.message_id,
            "username": session["username"],
            "content": content.strip(),
            "timestamp": response.timestamp
        }), 201
    except grpc.RpcError as error:
        if error.code() == grpc.StatusCode.UNAVAILABLE:
            return jsonify({
                "error": "El servidor gRPC no está disponible."
            }), 503
        return jsonify({
            "error": "No fue posible enviar el mensaje."
        }), 500
    finally:
        if channel:
            channel.close()


@app.errorhandler(404)
def not_found(error):
    return render_template("login.html"), 404


if __name__ == "__main__":
    database.init_db()
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=False
    )