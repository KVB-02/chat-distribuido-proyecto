"use strict";

// ============================================
// CONFIGURACIÓN
// ============================================
const API = "/api";
const USERNAME = window.CHAT_USERNAME;

let currentRoomId = null;
let currentRoomName = "";
let currentRoomIsGroup = true;
let lastMessageIds = new Set();
let pollingMessages = false;
let pollingMembers = false;

// Estado para el modal de creación de grupos
let selectedParticipants = new Map(); // key: usernameLower, value: usernameOriginal
let searchDebounceTimer = null;

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

// Elementos del panel lateral derecho de miembros
const membersPanel = document.getElementById("members-panel");
const membersList = document.getElementById("members-list");
const membersTotalBadge = document.getElementById("members-total-badge");
const membersToggleCount = document.getElementById("members-toggle-count");
const membersRoomSubtitle = document.getElementById("members-room-subtitle");
const toggleMembersButton = document.getElementById("toggle-members-button");

// Elementos de Crear Grupo
const openCreateGroupButton = document.getElementById("open-create-group-button");
const createGroupModal = document.getElementById("create-group-modal");
const closeCreateGroupModal = document.getElementById("close-create-group-modal");
const cancelCreateGroupButton = document.getElementById("cancel-create-group-button");
const createGroupForm = document.getElementById("create-group-form");
const groupNameInput = document.getElementById("group-name-input");
const participantSearchInput = document.getElementById("participant-search-input");
const userSearchResults = document.getElementById("user-search-results");
const selectedParticipantsList = document.getElementById("selected-participants-list");
const selectedParticipantsCount = document.getElementById("selected-participants-count");
const createGroupFeedback = document.getElementById("create-group-feedback");
const submitCreateGroupButton = document.getElementById("submit-create-group-button");

// Elementos de Salir del Grupo
const leaveGroupButton = document.getElementById("leave-group-button");
const leaveGroupModal = document.getElementById("leave-group-modal");
const closeLeaveGroupModal = document.getElementById("close-leave-group-modal");
const cancelLeaveGroupButton = document.getElementById("cancel-leave-group-button");
const confirmLeaveGroupButton = document.getElementById("confirm-leave-group-button");
const leaveGroupTargetName = document.getElementById("leave-group-target-name");

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
        const err = new Error(
            data.error || `Error en la petición: ${response.status}`
        );
        err.status = response.status;
        throw err;
    }

    return data;
}

// ============================================
// NOTIFICACIONES
// ============================================
let notificationTimer = null;

function showNotification(message, isSuccess = false) {
    notification.textContent = message;
    notification.classList.toggle("success", Boolean(isSuccess));
    notification.classList.remove("hidden");
    clearTimeout(notificationTimer);
    notificationTimer = setTimeout(() => {
        notification.classList.add("hidden");
    }, 4500);
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
// PANEL DE MIEMBROS (RESPONSIVO)
// ============================================
if (toggleMembersButton && membersPanel) {
    toggleMembersButton.addEventListener("click", () => {
        const isOpen = membersPanel.classList.toggle("open");
        toggleMembersButton.setAttribute("aria-expanded", String(isOpen));
    });
}

// ============================================
// CARGAR SALAS Y GRUPOS
// ============================================
async function loadRooms() {
    try {
        const data = await apiRequest(`${API}/rooms`);
        setConnectionStatus(true);
        const rooms = data.rooms || [];
        renderRooms(rooms);

        // Si el usuario estaba en un grupo que ya no está en su lista, limpiar vista
        if (currentRoomId !== null) {
            const stillVisible = rooms.some(r => Number(r.id) === Number(currentRoomId));
            if (!stillVisible) {
                resetActiveConversationView();
            }
        }
    } catch (error) {
        setConnectionStatus(false);
        roomsList.replaceChildren();
        const message = document.createElement("p");
        message.className = "muted";
        message.textContent = "No se pudieron cargar las conversaciones.";
        roomsList.appendChild(message);
        console.error("Error cargando salas:", error);
    }
}

function renderRooms(rooms) {
    roomsList.replaceChildren();

    if (rooms.length === 0) {
        const emptyMessage = document.createElement("p");
        emptyMessage.className = "muted";
        emptyMessage.textContent = "No tienes grupos activos. ¡Crea un grupo nuevo!";
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
        symbol.textContent = room.is_private ? "🔒" : "#";

        const name = document.createElement("span");
        name.className = "room-item-name";
        name.textContent = room.name;

        button.append(symbol, name);

        if (room.role === "admin") {
            const badge = document.createElement("span");
            badge.className = "room-admin-pill";
            badge.textContent = "Admin";
            button.appendChild(badge);
        }

        button.addEventListener("click", () => {
            joinRoom(room.id, room.name, room.is_group !== false);
        });

        roomsList.appendChild(button);
    });
}

// ============================================
// CREAR SALA RÁPIDA (FUNCIONALIDAD ORIGINAL)
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
        await joinRoom(data.id, data.name || name, true);
        showNotification("Sala creada correctamente.", true);
    } catch (error) {
        showNotification(error.message);
    }
});

// ============================================
// MODAL: CREAR GRUPO SELECCIONANDO USUARIOS
// ============================================
function showGroupModalFeedback(message, isError = true) {
    if (!message) {
        createGroupFeedback.textContent = "";
        createGroupFeedback.classList.add("hidden");
        return;
    }
    createGroupFeedback.textContent = message;
    createGroupFeedback.className = `modal-feedback ${isError ? "error" : "info"}`;
    createGroupFeedback.classList.remove("hidden");
}

function renderSelectedParticipants() {
    selectedParticipantsList.replaceChildren();
    selectedParticipantsCount.textContent = String(selectedParticipants.size);

    if (selectedParticipants.size === 0) {
        const empty = document.createElement("p");
        empty.className = "muted-small";
        empty.textContent = "Aún no has seleccionado otros participantes.";
        selectedParticipantsList.appendChild(empty);
        return;
    }

    selectedParticipants.forEach((username, key) => {
        const chip = document.createElement("div");
        chip.className = "participant-chip";

        const label = document.createElement("span");
        label.textContent = username;

        const removeBtn = document.createElement("button");
        removeBtn.type = "button";
        removeBtn.className = "chip-remove-btn";
        removeBtn.title = `Quitar a ${username}`;
        removeBtn.textContent = "×";
        removeBtn.addEventListener("click", () => {
            selectedParticipants.delete(key);
            renderSelectedParticipants();
            if (participantSearchInput.value.trim()) {
                performUserSearch(participantSearchInput.value.trim());
            }
        });

        chip.append(label, removeBtn);
        selectedParticipantsList.appendChild(chip);
    });
}

function addParticipantSelection(username) {
    if (!username) return;
    const clean = username.trim();
    if (!clean) return;

    if (clean.toLowerCase() === USERNAME.toLowerCase()) {
        showGroupModalFeedback("Ya estás incluido automáticamente como creador y administrador.");
        return;
    }

    const key = clean.toLowerCase();
    if (selectedParticipants.has(key)) {
        showGroupModalFeedback(`El usuario «${clean}» ya fue seleccionado.`);
        return;
    }

    selectedParticipants.set(key, clean);
    showGroupModalFeedback("");
    renderSelectedParticipants();
}

async function performUserSearch(queryText) {
    const cleanQuery = queryText.trim();
    if (!cleanQuery) {
        userSearchResults.replaceChildren();
        userSearchResults.classList.add("hidden");
        return;
    }

    try {
        const data = await apiRequest(
            `${API}/users/search?q=${encodeURIComponent(cleanQuery)}`
        );
        const users = data.users || [];
        userSearchResults.replaceChildren();
        userSearchResults.classList.remove("hidden");

        if (users.length === 0) {
            const notFound = document.createElement("div");
            notFound.className = "search-empty-item";
            notFound.textContent = `No existe ningún usuario que coincida con «${cleanQuery}». Puedes seguir buscando.`;
            userSearchResults.appendChild(notFound);
            return;
        }

        users.forEach(user => {
            const row = document.createElement("button");
            row.type = "button";
            row.className = "search-result-item";

            const isAlreadySelected = selectedParticipants.has(user.username.toLowerCase());
            if (isAlreadySelected) {
                row.classList.add("already-selected");
            }

            const left = document.createElement("div");
            left.className = "search-result-user";

            const dot = document.createElement("span");
            dot.className = `status-dot ${user.is_active ? "online" : "offline"}`;

            const uname = document.createElement("span");
            uname.className = "search-result-username";
            uname.textContent = user.username;

            left.append(dot, uname);

            const actionTag = document.createElement("span");
            actionTag.className = "search-result-action";
            actionTag.textContent = isAlreadySelected ? "Seleccionado ✓" : "+ Agregar";

            row.append(left, actionTag);

            row.addEventListener("click", () => {
                if (isAlreadySelected) {
                    showGroupModalFeedback(`El usuario «${user.username}» ya está en la lista de participantes.`);
                    return;
                }
                addParticipantSelection(user.username);
                participantSearchInput.value = "";
                userSearchResults.replaceChildren();
                userSearchResults.classList.add("hidden");
                participantSearchInput.focus();
            });

            userSearchResults.appendChild(row);
        });
    } catch (error) {
        showGroupModalFeedback(error.message);
    }
}

function openCreateGroupModalView() {
    selectedParticipants.clear();
    groupNameInput.value = "";
    participantSearchInput.value = "";
    userSearchResults.replaceChildren();
    userSearchResults.classList.add("hidden");
    showGroupModalFeedback("");
    renderSelectedParticipants();
    createGroupModal.classList.remove("hidden");
    groupNameInput.focus();
}

function closeCreateGroupModalView() {
    createGroupModal.classList.add("hidden");
    showGroupModalFeedback("");
}

if (openCreateGroupButton) {
    openCreateGroupButton.addEventListener("click", openCreateGroupModalView);
}
if (closeCreateGroupModal) {
    closeCreateGroupModal.addEventListener("click", closeCreateGroupModalView);
}
if (cancelCreateGroupButton) {
    cancelCreateGroupButton.addEventListener("click", closeCreateGroupModalView);
}

participantSearchInput.addEventListener("input", () => {
    clearTimeout(searchDebounceTimer);
    const query = participantSearchInput.value;
    searchDebounceTimer = setTimeout(() => {
        performUserSearch(query);
    }, 180);
});

participantSearchInput.addEventListener("keydown", async event => {
    if (event.key === "Enter") {
        event.preventDefault();
        const query = participantSearchInput.value.trim();
        if (!query) return;

        try {
            const data = await apiRequest(
                `${API}/users/search?q=${encodeURIComponent(query)}`
            );
            const users = data.users || [];
            const exactMatch = users.find(
                u => u.username.toLowerCase() === query.toLowerCase()
            );
            if (exactMatch) {
                addParticipantSelection(exactMatch.username);
                participantSearchInput.value = "";
                userSearchResults.replaceChildren();
                userSearchResults.classList.add("hidden");
            } else {
                showGroupModalFeedback(
                    `El usuario «${query}» no existe. Selecciona un usuario válido de la lista.`
                );
                await performUserSearch(query);
            }
        } catch (error) {
            showGroupModalFeedback(error.message);
        }
    }
});

createGroupForm.addEventListener("submit", async event => {
    event.preventDefault();
    showGroupModalFeedback("");

    const rawName = groupNameInput.value;
    if (!rawName || !rawName.trim()) {
        showGroupModalFeedback("El nombre del grupo es obligatorio y no puede estar compuesto solo por espacios.");
        groupNameInput.focus();
        return;
    }

    if (selectedParticipants.size === 0) {
        showGroupModalFeedback(
            "El sistema requiere seleccionar al menos otra persona además de ti para crear un grupo."
        );
        participantSearchInput.focus();
        return;
    }

    const participantsArray = Array.from(selectedParticipants.values());
    submitCreateGroupButton.disabled = true;
    submitCreateGroupButton.textContent = "Creando...";

    try {
        const data = await apiRequest(`${API}/groups`, {
            method: "POST",
            body: JSON.stringify({
                name: rawName.trim(),
                participants: participantsArray
            })
        });

        closeCreateGroupModalView();
        await loadRooms();
        await joinRoom(data.id, data.name, true);
        showNotification(`Grupo «${data.name}» creado correctamente.`, true);
    } catch (error) {
        showGroupModalFeedback(error.message);
    } finally {
        submitCreateGroupButton.disabled = false;
        submitCreateGroupButton.textContent = "Crear grupo";
    }
});

// ============================================
// ENTRAR EN UN GRUPO O SALA
// ============================================
async function joinRoom(roomId, roomName, isGroup = true) {
    try {
        const joinData = await apiRequest(`${API}/rooms/${roomId}/join`, {
            method: "POST"
        });

        currentRoomId = Number(roomId);
        currentRoomName = joinData.name || roomName;
        currentRoomIsGroup = joinData.is_group !== undefined ? Boolean(joinData.is_group) : Boolean(isGroup);
        lastMessageIds.clear();

        currentRoomTitle.textContent = `# ${currentRoomName}`;
        roomDescription.textContent = joinData.is_private
            ? "Grupo privado · Solo miembros autorizados"
            : "Grupo de conversación mediante gRPC";

        if (membersRoomSubtitle) {
            membersRoomSubtitle.textContent = `# ${currentRoomName}`;
        }

        // Mostrar el botón "Salir del grupo" únicamente dentro de grupos
        if (leaveGroupButton) {
            if (currentRoomIsGroup) {
                leaveGroupButton.classList.remove("hidden");
            } else {
                leaveGroupButton.classList.add("hidden");
            }
        }

        messageInput.disabled = false;
        sendButton.disabled = false;
        messageInput.placeholder = "Escribe un mensaje...";
        messagesContainer.replaceChildren();

        await Promise.all([
            loadMessages(true),
            loadRoomMembers(),
            loadRooms()
        ]);
        messageInput.focus();
    } catch (error) {
        showNotification(error.message);
    }
}

function resetActiveConversationView() {
    currentRoomId = null;
    currentRoomName = "";
    currentRoomIsGroup = false;
    lastMessageIds.clear();

    currentRoomTitle.textContent = "Selecciona una sala o grupo";
    roomDescription.textContent = "Mensajería distribuida mediante gRPC";
    if (membersRoomSubtitle) {
        membersRoomSubtitle.textContent = "Sin grupo seleccionado";
    }
    if (leaveGroupButton) {
        leaveGroupButton.classList.add("hidden");
    }

    messageInput.value = "";
    messageInput.disabled = true;
    sendButton.disabled = true;

    messagesContainer.replaceChildren();
    const welcome = document.createElement("div");
    welcome.className = "welcome-message";
    const icon = document.createElement("div");
    icon.className = "welcome-icon";
    icon.textContent = "💬";
    const title = document.createElement("h2");
    title.textContent = "Bienvenido al chat";
    const desc = document.createElement("p");
    desc.textContent = "Selecciona un grupo o crea uno nuevo para comenzar a conversar.";
    welcome.append(icon, title, desc);
    messagesContainer.appendChild(welcome);

    membersList.replaceChildren();
    const muted = document.createElement("p");
    muted.className = "muted";
    muted.textContent = "Selecciona un grupo para ver los usuarios que pertenecen a él.";
    membersList.appendChild(muted);
    if (membersTotalBadge) membersTotalBadge.textContent = "0";
    if (membersToggleCount) membersToggleCount.textContent = "0";
}

// ============================================
// SALIR DE UN GRUPO (CON CONFIRMACIÓN)
// ============================================
function openLeaveGroupModalView() {
    if (currentRoomId === null || !currentRoomIsGroup) {
        return;
    }
    leaveGroupTargetName.textContent = `#${currentRoomName}`;
    leaveGroupModal.classList.remove("hidden");
}

function closeLeaveGroupModalView() {
    leaveGroupModal.classList.add("hidden");
}

if (leaveGroupButton) {
    leaveGroupButton.addEventListener("click", openLeaveGroupModalView);
}
if (closeLeaveGroupModal) {
    closeLeaveGroupModal.addEventListener("click", closeLeaveGroupModalView);
}
if (cancelLeaveGroupButton) {
    cancelLeaveGroupButton.addEventListener("click", closeLeaveGroupModalView);
}

if (confirmLeaveGroupButton) {
    confirmLeaveGroupButton.addEventListener("click", async () => {
        if (currentRoomId === null) {
            closeLeaveGroupModalView();
            return;
        }

        const roomIdToLeave = currentRoomId;
        confirmLeaveGroupButton.disabled = true;
        confirmLeaveGroupButton.textContent = "Saliendo...";

        try {
            const response = await apiRequest(
                `${API}/rooms/${roomIdToLeave}/leave`,
                { method: "POST" }
            );
            closeLeaveGroupModalView();
            resetActiveConversationView();
            await loadRooms();
            showNotification(response.message || "Has salido del grupo.", true);
        } catch (error) {
            closeLeaveGroupModalView();
            showNotification(error.message);
        } finally {
            confirmLeaveGroupButton.disabled = false;
            confirmLeaveGroupButton.textContent = "Salir del grupo";
        }
    });
}

// ============================================
// CARGAR Y MOSTRAR MIEMBROS DE LA SALA
// ============================================
function createMemberElement(member) {
    const item = document.createElement("div");
    item.className = "member-item";
    if (!member.is_active) {
        item.classList.add("inactive");
    }

    const avatarWrapper = document.createElement("div");
    avatarWrapper.className = "member-avatar-wrapper";

    const avatar = document.createElement("div");
    avatar.className = "avatar small";
    const initial = member.username ? member.username.charAt(0).toUpperCase() : "?";
    avatar.textContent = initial;

    const statusDot = document.createElement("span");
    statusDot.className = `status-dot ${member.is_active ? "online" : "offline"}`;
    statusDot.title = member.is_active ? "Activo (Conectado)" : "Inactivo (Desconectado)";

    avatarWrapper.append(avatar, statusDot);

    const meta = document.createElement("div");
    meta.className = "member-meta";

    const nameRow = document.createElement("div");
    nameRow.className = "member-name-row";

    const name = document.createElement("span");
    name.className = "member-name";
    name.textContent = member.username;
    nameRow.appendChild(name);

    if (member.username === USERNAME) {
        const youTag = document.createElement("span");
        youTag.className = "member-you-tag";
        youTag.textContent = "Tú";
        nameRow.appendChild(youTag);
    }

    if (member.role === "admin") {
        const adminTag = document.createElement("span");
        adminTag.className = "member-admin-tag";
        adminTag.textContent = "Admin";
        nameRow.appendChild(adminTag);
    }

    const statusText = document.createElement("span");
    statusText.className = `member-status-text ${member.is_active ? "online" : "offline"}`;
    statusText.textContent = member.is_active ? "Activo" : "Inactivo";

    meta.append(nameRow, statusText);
    item.append(avatarWrapper, meta);
    return item;
}

function renderMembersGroup(titleText, members) {
    const group = document.createElement("section");
    group.className = "members-group";

    const heading = document.createElement("h4");
    heading.className = "members-group-title";
    heading.textContent = `${titleText} — ${members.length}`;
    group.appendChild(heading);

    members.forEach(member => {
        group.appendChild(createMemberElement(member));
    });

    return group;
}

function renderRoomMembers(members) {
    membersList.replaceChildren();
    const total = members.length;

    if (membersTotalBadge) {
        membersTotalBadge.textContent = String(total);
    }
    if (membersToggleCount) {
        membersToggleCount.textContent = String(total);
    }

    if (total === 0) {
        const empty = document.createElement("p");
        empty.className = "muted";
        empty.textContent = "Aún no hay miembros registrados en este grupo.";
        membersList.appendChild(empty);
        return;
    }

    const activeMembers = members.filter(member => Boolean(member.is_active));
    const inactiveMembers = members.filter(member => !member.is_active);

    if (activeMembers.length > 0) {
        membersList.appendChild(
            renderMembersGroup("Activos", activeMembers)
        );
    }
    if (inactiveMembers.length > 0) {
        membersList.appendChild(
            renderMembersGroup("Inactivos", inactiveMembers)
        );
    }
}

async function loadRoomMembers() {
    if (currentRoomId === null || pollingMembers) {
        return;
    }
    pollingMembers = true;
    try {
        const data = await apiRequest(
            `${API}/rooms/${currentRoomId}/members`
        );
        renderRoomMembers(data.members || []);
    } catch (error) {
        if (error.status === 403) {
            resetActiveConversationView();
            loadRooms();
        }
        console.error("Error consultando miembros de la sala:", error);
    } finally {
        pollingMembers = false;
    }
}

// ============================================
// MOSTRAR MENSAJES
// ============================================
function renderMessage(message) {
    const article = document.createElement("article");
    article.className = "message";

    if (message.username === "Sistema") {
        article.classList.add("system-message");
    } else if (message.username === USERNAME) {
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

        let addedNew = false;
        messages.forEach(message => {
            const id = Number(message.id);
            if (lastMessageIds.has(id)) {
                return;
            }
            // Si había cartel de bienvenida sin mensajes, quitarlo al llegar el primero
            const welcomePlaceholder = messagesContainer.querySelector(".welcome-message");
            if (welcomePlaceholder) {
                welcomePlaceholder.remove();
            }
            lastMessageIds.add(id);
            const element = renderMessage(message);
            messagesContainer.appendChild(element);
            addedNew = true;
        });

        if (messages.length === 0 && initialLoad) {
            const empty = document.createElement("div");
            empty.className = "welcome-message";
            const title = document.createElement("h2");
            title.textContent = "¡Comienza la conversación!";
            const description = document.createElement("p");
            description.textContent = "Todavía no hay mensajes en este grupo.";
            empty.append(title, description);
            messagesContainer.appendChild(empty);
        }

        if (addedNew) {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    } catch (error) {
        if (error.status === 403) {
            resetActiveConversationView();
            loadRooms();
            showNotification(error.message);
        } else {
            setConnectionStatus(false);
        }
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
        showNotification("Primero selecciona un grupo o sala.");
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
        await loadRoomMembers();
        messageInput.focus();
    } catch (error) {
        showNotification(error.message);
        if (error.status === 403) {
            resetActiveConversationView();
            await loadRooms();
        }
    } finally {
        sendButton.disabled = currentRoomId === null;
    }
});

// ============================================
// ACTUALIZACIÓN PERIÓDICA
// ============================================
setInterval(() => {
    loadMessages();
}, 1000);

setInterval(() => {
    loadRoomMembers();
}, 3000);

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