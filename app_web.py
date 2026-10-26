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
    session.clear()
    flash("Has cerrado sesión.", "success")
    return redirect(url_for("login"))


@app.route("/chat")
@login_required
def chat():
    return render_template(
        "chat.html",
        username=session["username"]
    )


@app.route("/api/rooms", methods=["GET"])
@login_required
def api_list_rooms():
    channel = None

    try:
        channel, stub = get_grpc_stub()

        response = stub.ListRooms(timeout=3)

        rooms = [
            {
                "id": room.room_id,
                "name": room.room_name
            }
            for room in response.rooms
        ]

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
    room_name = data.get("name", "").strip()

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
            "message": response.message
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

        response = stub.CreateRoom(
            chat_pb2.RoomRequest(
                room_name=_room_name_from_id(room_id, stub),
                username=session["username"]
            ),
            timeout=3
        )

        if not response.success:
            return jsonify({"error": response.message}), 400

        return jsonify({
            "id": response.room_id,
            "message": "Has entrado en la sala."
        })

    except ValueError:
        return jsonify({"error": "La sala no existe."}), 404

    except grpc.RpcError:
        return jsonify({
            "error": "No se puede conectar con el servidor gRPC."
        }), 503

    finally:
        if channel:
            channel.close()


def _room_name_from_id(room_id, stub):
    """Busca el nombre de una sala a partir de su identificador."""
    response = stub.ListRooms(timeout=3)

    for room in response.rooms:
        if room.room_id == room_id:
            return room.room_name

    raise ValueError("La sala no existe.")


@app.route("/api/rooms/<int:room_id>/messages", methods=["GET"])
@login_required
def api_get_messages(room_id):
    channel = None

    try:
        channel, stub = get_grpc_stub()

        response = stub.GetMessages(
            chat_pb2.HistoryRequest(
                room_id=room_id,
                username=session["username"],
                limit=100
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
                "error": "Debes entrar en la sala para consultar sus mensajes."
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
            return jsonify({"error": response.message}), 400

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
