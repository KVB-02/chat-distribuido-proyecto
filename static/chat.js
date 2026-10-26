"use strict";

// ============================================
// CONFIGURACIÓN
// ============================================

const API = "/api";
const USERNAME = window.CHAT_USERNAME;

let currentRoomId = null;
let currentRoomName = "";
let lastMessageIds = new Set();
let pollingMessages = false;

// ============================================
// ELEMENTOS HTML
// ============================================

const roomsList = document.getElementById("rooms-list");
const messagesContainer = document.getElementById("messages-container");

const currentRoomTitle = document.getElementById("current-room-name");
const roomDescription = document.getElementById("room-description");

const createRoomButton = document.getElementById("create-room-button");
const createRoomForm = document.getElementById("create-room-form");
const roomNameInput = document.getElementById("room-name");

const messageForm = document.getElementById("message-form");
const messageInput = document.getElementById("message-input");
const sendButton = document.getElementById("send-button");

const connectionStatus = document.getElementById("connection-status");
const notification = document.getElementById("notification");

// ============================================
// COMUNICACIÓN CON FLASK
// ============================================

async function apiRequest(url, options = {}) {
    const response = await fetch(url, {
        ...options,
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {})
        }
    });

    let data;

    try {
        data = await response.json();
    } catch {
        data = {};
    }

    if (!response.ok) {
        throw new Error(
            data.error || `Error en la petición: ${response.status}`
        );
    }

    return data;
}

// ============================================
// NOTIFICACIONES
// ============================================

let notificationTimer = null;

function showNotification(message) {
    notification.textContent = message;
    notification.classList.remove("hidden");

    clearTimeout(notificationTimer);

    notificationTimer = setTimeout(() => {
        notification.classList.add("hidden");
    }, 4000);
}

// ============================================
// ESTADO DE CONEXIÓN
// ============================================

function setConnectionStatus(connected) {
    if (connected) {
        connectionStatus.textContent = "Servidor conectado";
        connectionStatus.classList.remove("offline");
    } else {
        connectionStatus.textContent = "Sin conexión";
        connectionStatus.classList.add("offline");
    }
}

// ============================================
// CARGAR SALAS
// ============================================

async function loadRooms() {
    try {
        const data = await apiRequest(`${API}/rooms`);

        setConnectionStatus(true);
        renderRooms(data.rooms || []);

    } catch (error) {
        setConnectionStatus(false);

        roomsList.replaceChildren();

        const message = document.createElement("p");
        message.className = "muted";
        message.textContent = "No se pudieron cargar las salas.";

        roomsList.appendChild(message);

        console.error("Error cargando salas:", error);
    }
}

function renderRooms(rooms) {
    roomsList.replaceChildren();

    if (rooms.length === 0) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "muted";
        emptyMessage.textContent = "Todavía no hay salas. ¡Crea la primera!";

        roomsList.appendChild(emptyMessage);
        return;
    }

    rooms.forEach(room => {
        const button = document.createElement("button");

        button.type = "button";
        button.className = "room-item";

        if (Number(room.id) === Number(currentRoomId)) {
            button.classList.add("active");
        }

        const symbol = document.createElement("span");
        symbol.className = "room-symbol";
        symbol.textContent = "#";

        const name = document.createElement("span");
        name.textContent = room.name;

        button.append(symbol, name);

        button.addEventListener("click", () => {
            joinRoom(room.id, room.name);
        });

        roomsList.appendChild(button);
    });
}

// ============================================
// CREAR SALAS
// ============================================

createRoomButton.addEventListener("click", () => {
    createRoomForm.classList.toggle("hidden");

    if (!createRoomForm.classList.contains("hidden")) {
        roomNameInput.focus();
    }
});

createRoomForm.addEventListener("submit", async event => {
    event.preventDefault();

    const name = roomNameInput.value.trim();

    if (!name) {
        showNotification("Escribe el nombre de la sala.");
        return;
    }

    try {
        const data = await apiRequest(`${API}/rooms`, {
            method: "POST",
            body: JSON.stringify({ name })
        });

        roomNameInput.value = "";
        createRoomForm.classList.add("hidden");

        await loadRooms();

        await joinRoom(data.id, data.name || name);

        showNotification("Sala creada correctamente.");

    } catch (error) {
        showNotification(error.message);
    }
});

// ============================================
// ENTRAR EN UNA SALA
// ============================================

async function joinRoom(roomId, roomName) {
    try {
        await apiRequest(`${API}/rooms/${roomId}/join`, {
            method: "POST"
        });

        currentRoomId = Number(roomId);
        currentRoomName = roomName;

        lastMessageIds.clear();

        currentRoomTitle.textContent = `# ${roomName}`;
        roomDescription.textContent =
            "Los mensajes se consultan mediante gRPC.";

        messageInput.disabled = false;
        sendButton.disabled = false;

        messageInput.placeholder = "Escribe un mensaje...";
        messagesContainer.replaceChildren();

        await loadMessages(true);
        await loadRooms();

        messageInput.focus();

    } catch (error) {
        showNotification(error.message);
    }
}

// ============================================
// MOSTRAR MENSAJES
// ============================================

function renderMessage(message) {
    const article = document.createElement("article");

    article.className = "message";

    if (message.username === USERNAME) {
        article.classList.add("own");
    }

    const header = document.createElement("div");
    header.className = "message-header";

    const author = document.createElement("span");
    author.className = "message-author";
    author.textContent = message.username;

    const time = document.createElement("span");
    time.className = "message-time";

    if (message.timestamp) {
        const date = new Date(message.timestamp);

        time.textContent = Number.isNaN(date.getTime())
            ? message.timestamp
            : date.toLocaleString("es-CO", {
                dateStyle: "short",
                timeStyle: "short"
            });
    }

    header.append(author, time);

    const content = document.createElement("div");
    content.className = "message-content";

    // textContent evita interpretar mensajes como código HTML.
    content.textContent = message.content;

    article.append(header, content);

    return article;
}

async function loadMessages(initialLoad = false) {
    if (currentRoomId === null || pollingMessages) {
        return;
    }

    pollingMessages = true;

    try {
        const data = await apiRequest(
            `${API}/rooms/${currentRoomId}/messages`
        );

        setConnectionStatus(true);

        const messages = data.messages || [];

        if (initialLoad) {
            messagesContainer.replaceChildren();
            lastMessageIds.clear();
        }

        messages.forEach(message => {
            const id = Number(message.id);

            if (lastMessageIds.has(id)) {
                return;
            }

            lastMessageIds.add(id);

            const element = renderMessage(message);
            messagesContainer.appendChild(element);
        });

        if (messages.length === 0 && initialLoad) {
            const empty = document.createElement("div");

            empty.className = "welcome-message";

            const title = document.createElement("h2");
            title.textContent = "¡Comienza la conversación!";

            const description = document.createElement("p");
            description.textContent =
                "Todavía no hay mensajes en esta sala.";

            empty.append(title, description);
            messagesContainer.appendChild(empty);
        }

        if (messages.length > 0) {
            messagesContainer.scrollTop =
                messagesContainer.scrollHeight;
        }

    } catch (error) {
        setConnectionStatus(false);
        console.error("Error consultando mensajes:", error);
    } finally {
        pollingMessages = false;
    }
}

// ============================================
// ENVIAR MENSAJES
// ============================================

messageForm.addEventListener("submit", async event => {
    event.preventDefault();

    if (currentRoomId === null) {
        showNotification("Primero selecciona una sala.");
        return;
    }

    const content = messageInput.value.trim();

    if (!content) {
        return;
    }

    sendButton.disabled = true;

    try {
        await apiRequest(
            `${API}/rooms/${currentRoomId}/messages`,
            {
                method: "POST",
                body: JSON.stringify({ content })
            }
        );

        messageInput.value = "";

        await loadMessages();

        messageInput.focus();

    } catch (error) {
        showNotification(error.message);
    } finally {
        sendButton.disabled = currentRoomId === null;
    }
});

// ============================================
// ACTUALIZACIÓN PERIÓDICA
// ============================================

// Consulta nuevos mensajes cada segundo.
// Esto simula una actualización en tiempo real
// mediante consultas HTTP a Flask y llamadas gRPC.

setInterval(() => {
    loadMessages();
}, 1000);

// Actualiza la lista de salas cada cinco segundos.

setInterval(() => {
    loadRooms();
}, 5000);

// ============================================
// INICIALIZACIÓN
// ============================================

async function initializeChat() {
    await loadRooms();

    console.log("Chat distribuido iniciado.");
    console.log("Usuario:", USERNAME);
}

initializeChat();