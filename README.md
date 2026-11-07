# Chat Distribuido

Aplicación web de chat con Flask, gRPC y SQLite. Incluye salas públicas y privadas, invitaciones a usuarios conectados, presencia, historial de mensajes y control de acceso.

## Requisitos
- Python 3.10 o superior
- Dependencias de `requirements.txt`

## Instalación (Windows PowerShell)
Abre PowerShell en esta carpeta y ejecuta:

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

## Ejecución
Abre **dos terminales** en la carpeta del proyecto y activa el entorno virtual en ambas.

Terminal 1 (servidor gRPC):
```powershell
python servidor_grpc.py
```

Terminal 2 (aplicación web):
```powershell
python app_web.py
```

Abre `http://localhost:5000` en el navegador. Registra dos o más usuarios en navegadores distintos para probar presencia e invitaciones.

## Uso de salas
- **Pública:** cualquier usuario registrado puede verla y unirse.
- **Privada:** solo el creador y los usuarios invitados pueden verla y entrar.
- El creador queda como administrador y puede invitar usuarios conectados desde el botón **Invitar**.
- Los mensajes se envían y consultan mediante el servicio gRPC y se guardan en SQLite.

La base `chat.db` se crea automáticamente al iniciar si no existe. Si ya tienes datos, conserva tu archivo `chat.db`.
