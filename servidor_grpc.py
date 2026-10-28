import logging
from concurrent import futures
import grpc
import chat_pb2
import chat_pb2_grpc
import database

HOST = "0.0.0.0"
PORT = 50051
MAX_WORKERS = 20


class ChatService(chat_pb2_grpc.ChatServiceServicer):
    """Implementa las operaciones remotas del chat distribuido."""

    def CreateRoom(self, request, context):
        try:
            room, error = database.get_or_create_room(
                request.room_name,
                request.username
            )
            if error:
                return chat_pb2.RoomResponse(
                    success=False,
                    message=error,
                    room_id=0
                )
            return chat_pb2.RoomResponse(
                success=True,
                message="Sala creada o encontrada correctamente.",
                room_id=room["id"]
            )
        except Exception:
            logging.exception("Error al crear o consultar una sala")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible procesar la sala."
            )

    def CreateGroup(self, request, context):
        try:
            group, error = database.create_group_with_members(
                request.group_name,
                request.creator_username,
                list(request.participants)
            )
            if error:
                return chat_pb2.RoomResponse(
                    success=False,
                    message=error,
                    room_id=0
                )
            return chat_pb2.RoomResponse(
                success=True,
                message="Grupo creado correctamente.",
                room_id=group["id"]
            )
        except Exception:
            logging.exception("Error al crear un grupo")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible crear el grupo."
            )

    def LeaveRoom(self, request, context):
        try:
            result, error = database.leave_group(
                request.room_id,
                request.username
            )
            if error:
                return chat_pb2.LeaveRoomResponse(
                    success=False,
                    message=error,
                    new_admin=""
                )
            return chat_pb2.LeaveRoomResponse(
                success=True,
                message=f"Has salido del grupo «{result['room_name']}».",
                new_admin=result.get("new_admin") or ""
            )
        except Exception:
            logging.exception("Error al abandonar el grupo")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible abandonar el grupo."
            )

    def SearchUsers(self, request, context):
        try:
            users = database.search_users(
                request.query,
                exclude_username=request.exclude_username
            )
            return chat_pb2.SearchUsersResponse(
                users=[
                    chat_pb2.UserSummary(
                        user_id=u["id"],
                        username=u["username"],
                        is_active=u["is_active"]
                    )
                    for u in users
                ]
            )
        except Exception:
            logging.exception("Error al buscar usuarios")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible buscar usuarios."
            )

    def ListRooms(self, request, context):
        try:
            rooms = database.list_rooms()
            return chat_pb2.RoomList(
                rooms=[
                    chat_pb2.RoomInfo(
                        room_id=room["id"],
                        room_name=room["name"]
                    )
                    for room in rooms
                ]
            )
        except Exception:
            logging.exception("Error al consultar las salas")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible consultar las salas."
            )

    def SendMessage(self, request, context):
        try:
            message, error = database.save_message(
                request.room_id,
                request.username,
                request.content
            )
            if error:
                return chat_pb2.MessageResponse(
                    success=False,
                    message=error,
                    message_id=0,
                    timestamp=""
                )
            return chat_pb2.MessageResponse(
                success=True,
                message="Mensaje guardado correctamente.",
                message_id=message["id"],
                timestamp=message["timestamp"]
            )
        except Exception:
            logging.exception("Error al guardar un mensaje")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible guardar el mensaje."
            )

    def GetMessages(self, request, context):
        try:
            messages, error = database.get_messages(
                request.room_id,
                request.username,
                request.limit
            )
            if error:
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    error
                )
            return chat_pb2.MessageList(
                messages=[
                    chat_pb2.ChatMessage(
                        message_id=message["id"],
                        room_id=message["room_id"],
                        username=message["username"],
                        content=message["content"],
                        timestamp=message["timestamp"]
                    )
                    for message in messages
                ]
            )
        except grpc.RpcError:
            raise
        except Exception:
            logging.exception("Error al consultar el historial")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible consultar los mensajes."
            )

    def GetRoomMembers(self, request, context):
        try:
            members, error = database.get_room_members(
                request.room_id,
                request.username
            )
            if error:
                context.abort(
                    grpc.StatusCode.PERMISSION_DENIED,
                    error
                )

            proto_members = []
            for member in members:
                kwargs = {
                    "user_id": member["user_id"],
                    "username": member["username"],
                    "is_active": member["is_active"],
                    "last_seen": member["last_seen"]
                }
                if "role" in chat_pb2.RoomMember.DESCRIPTOR.fields_by_name:
                    kwargs["role"] = member.get("role", "member")
                proto_members.append(chat_pb2.RoomMember(**kwargs))

            return chat_pb2.RoomMembersList(members=proto_members)
        except grpc.RpcError:
            raise
        except Exception:
            logging.exception("Error al consultar los miembros de la sala")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible consultar los miembros de la sala."
            )

    def UpdatePresence(self, request, context):
        try:
            success = database.update_user_presence(
                request.username,
                is_online=request.is_online
            )
            return chat_pb2.PresenceResponse(success=success)
        except Exception:
            logging.exception("Error al actualizar la presencia del usuario")
            context.abort(
                grpc.StatusCode.INTERNAL,
                "No fue posible actualizar la presencia."
            )


def serve():
    """Inicia el servidor gRPC."""
    database.init_db()
    server = grpc.server(
        futures.ThreadPoolExecutor(max_workers=MAX_WORKERS)
    )
    chat_pb2_grpc.add_ChatServiceServicer_to_server(
        ChatService(),
        server
    )
    server.add_insecure_port(f"{HOST}:{PORT}")
    server.start()
    print("=" * 55)
    print("SERVIDOR gRPC DEL CHAT DISTRIBUIDO")
    print(f"Escuchando en {HOST}:{PORT}")
    print("Estado: ACTIVO")
    print("Presiona Ctrl+C para detenerlo.")
    print("=" * 55)
    try:
        server.wait_for_termination()
    except KeyboardInterrupt:
        print("\nDeteniendo el servidor gRPC...")
        server.stop(grace=3).wait()
        print("Servidor detenido correctamente.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    serve()