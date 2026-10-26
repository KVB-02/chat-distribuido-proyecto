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