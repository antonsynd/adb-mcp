/* MIT License
 *
 * Copyright (c) 2025 Mike Chambers
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 * AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 * LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 * OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 */

const { entrypoints, UI } = require("uxp");
const {
    checkRequiresActiveDocument,
    parseAndRouteCommand,
} = require("./commands/index.js");

const { hasActiveSelection, generateDocumentInfo } = require("./commands/utils.js");

const { getLayers } = require("./commands/layers.js").commandHandlers;

const { io } = require("./socket.io.js");
const logger = require("./logger.js");
const app = require("photoshop").app;

const APPLICATION = "photoshop";
const PROXY_URL = "http://localhost:3001";
const TOKEN_URL = "http://localhost:3001/__token";

let socket = null;

function diagnose(context, errorMsg) {
    var msg = String(errorMsg).toLowerCase();
    var hints = [];

    if (context === "auth") {
        if (msg.indexOf("network request failed") !== -1 || msg.indexOf("fetch") !== -1) {
            hints.push("The proxy server is not running.");
            hints.push("Start it: cd adb-proxy-socket && node proxy.js");
            hints.push("Or start the MCP server (it auto-launches the proxy).");
        } else if (msg.indexOf("http") !== -1) {
            hints.push("Proxy is running but the token endpoint returned an error.");
            hints.push("Try restarting the proxy server.");
        }
    }

    if (context === "socket") {
        if (msg.indexOf("timeout") !== -1) {
            hints.push("Socket.IO handshake timed out.");
            hints.push("Check manifest.json has ws://localhost:3001 in network domains.");
            hints.push("Try restarting the proxy and clicking Retry.");
        } else if (msg.indexOf("unauthorized") !== -1) {
            hints.push("Auth token was rejected — the proxy generates a new token on each restart.");
            hints.push("Click Retry to fetch a fresh token.");
        } else if (msg.indexOf("websocket") !== -1) {
            hints.push("WebSocket transport failed.");
            hints.push("The plugin will fall back to HTTP polling automatically.");
        } else if (msg.indexOf("xhr") !== -1 || msg.indexOf("polling") !== -1) {
            hints.push("HTTP polling transport failed.");
            hints.push("Check that http://localhost:3001 is accessible.");
        }
    }

    if (context === "disconnect") {
        if (msg.indexOf("transport close") !== -1 || msg.indexOf("transport error") !== -1) {
            hints.push("The proxy server may have stopped or crashed.");
            hints.push("Check the proxy terminal for errors, then click Retry.");
        } else if (msg.indexOf("io server disconnect") !== -1) {
            hints.push("The proxy forcefully disconnected this client.");
            hints.push("Check proxy logs for rate-limiting or connection-limit messages.");
        } else if (msg.indexOf("ping timeout") !== -1) {
            hints.push("Proxy stopped responding to heartbeats.");
            hints.push("The proxy process may be frozen or overloaded.");
        }
    }

    if (context === "command") {
        if (msg.indexOf("no active document") !== -1 || msg.indexOf("document is null") !== -1) {
            hints.push("Open or create a document in Photoshop first.");
        }
    }

    for (var i = 0; i < hints.length; i++) {
        logger.hint(hints[i]);
    }
}

async function fetchAuthToken() {
    logger.debug("Fetching auth token from " + TOKEN_URL);
    const response = await fetch(TOKEN_URL);
    if (!response.ok) {
        throw new Error("HTTP " + response.status);
    }
    logger.debug("Auth token received");
    return await response.text();
}

const onCommandPacket = async (packet) => {
    let command = packet.command;

    let out = {
        senderId: packet.senderId,
    };

    try {
        checkRequiresActiveDocument(command);

        let response = await parseAndRouteCommand(command);

        out.response = response;
        out.status = "SUCCESS";

        let activeDocument = app.activeDocument
        let doc = generateDocumentInfo(activeDocument, activeDocument)
        out.document = doc;

        out.layers = await getLayers();

        out.hasActiveSelection = hasActiveSelection();

        logger.info("Command OK: " + command.action);
    } catch (e) {
        out.status = "FAILURE";
        out.message = "Error calling " + command.action + " : " + e;
        logger.error("Command FAILED: " + command.action + " — " + e);
        diagnose("command", String(e));
    }

    return out;
};

async function connectToServer() {
    logger.info("Connecting to proxy at " + PROXY_URL);
    setConnectionStatus("connecting");

    let authToken;
    try {
        authToken = await fetchAuthToken();
    } catch (e) {
        logger.error("Failed to fetch auth token: " + (e.message || e));
        diagnose("auth", e.message || e);
        setConnectionStatus("error");
        return;
    }

    logger.debug("Initializing Socket.IO (polling + websocket transport)");
    socket = io(PROXY_URL, {
        transports: ["polling", "websocket"],
        auth: { token: authToken },
    });

    socket.on("connect", () => {
        setConnectionStatus("connected");
        logger.info("Connected to proxy (socket ID: " + socket.id + ")");
        socket.emit("register", { application: APPLICATION });
        logger.info("Registered as '" + APPLICATION + "'");
    });

    socket.on("command_packet", async (packet) => {
        var action = packet && packet.command ? packet.command.action : "unknown";
        logger.info("Command received: " + action);
        logger.debug("Command payload:", packet);

        let response = await onCommandPacket(packet);
        sendResponsePacket(response);
    });

    socket.on("registration_response", (data) => {
        logger.info("Registration acknowledged:", data);
    });

    socket.on("connect_error", (error) => {
        setConnectionStatus("error");
        logger.error("Connection error: " + (error.message || error));
        diagnose("socket", error.message || error);
    });

    socket.on("disconnect", (reason) => {
        setConnectionStatus("disconnected");
        logger.warn("Disconnected from proxy: " + reason);
        if (reason !== "io client disconnect") {
            diagnose("disconnect", reason);
        }
    });

    return socket;
}

function disconnectFromServer() {
    if (socket && socket.connected) {
        socket.disconnect();
        logger.info("Disconnected from proxy (user-initiated)");
    }
}

function sendResponsePacket(packet) {
    if (socket && socket.connected) {
        socket.emit("command_packet_response", {
            packet: packet,
        });
        return true;
    }
    return false;
}

function sendCommand(command) {
    if (socket && socket.connected) {
        socket.emit("app_command", {
            application: APPLICATION,
            command: command,
        });
        return true;
    }
    return false;
}

let onInterval = async () => {
    let commands = await fetchCommands();

    await parseAndRouteCommands(commands);
};

let fetchCommands = async () => {
    try {
        let url = `http://127.0.0.1:3030/commands/get/${APPLICATION}/`;

        const fetchOptions = {
            method: "GET",
            headers: {
                Accept: "application/json",
            },
        };

        // Make the fetch request
        const response = await fetch(url, fetchOptions);

        // Check if the request was successful
        if (!response.ok) {
            throw new Error(`HTTP error! Status: ${response.status}`);
        }

        let r = await response.json();

        if (r.status != "SUCCESS") {
            throw new Error(`API Request error! Status: ${response.message}`);
        }

        return r.commands;
    } catch (error) {
        logger.error("Error fetching commands: " + (error.message || error));
        throw error;
    }
};

entrypoints.setup({
    panels: {
        vanilla: {
            show(node) {},
        },
    },
});

function setConnectionStatus(state) {
    const btn = document.getElementById("btnStart");
    const dot = document.getElementById("statusIndicator");
    const text = document.getElementById("statusText");

    dot.className = "status-dot";

    switch (state) {
        case "disconnected":
            dot.classList.add("disconnected");
            text.textContent = "Disconnected";
            btn.textContent = "Connect";
            btn.disabled = false;
            break;
        case "connecting":
            dot.classList.add("connecting");
            text.textContent = "Connecting...";
            btn.textContent = "Cancel";
            btn.disabled = false;
            break;
        case "connected":
            dot.classList.add("connected");
            text.textContent = "Connected";
            btn.textContent = "Disconnect";
            btn.disabled = false;
            break;
        case "error":
            dot.classList.add("error");
            text.textContent = "Connection failed";
            btn.textContent = "Retry";
            btn.disabled = false;
            break;
    }
}

document.getElementById("btnStart").addEventListener("click", () => {
    if (socket && (socket.connected || socket.active)) {
        disconnectFromServer();
        setConnectionStatus("disconnected");
    } else {
        connectToServer();
    }
});

const CONNECT_ON_LAUNCH = "connectOnLaunch";
// Save checkbox state in localStorage
document
    .getElementById("chkConnectOnLaunch")
    .addEventListener("change", function (event) {
        window.localStorage.setItem(
            CONNECT_ON_LAUNCH,
            JSON.stringify(event.target.checked)
        );
    });

// Retrieve checkbox state
const getConnectOnLaunch = () => {
    return JSON.parse(window.localStorage.getItem(CONNECT_ON_LAUNCH)) || false;
};

// Set checkbox state on page load
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("chkConnectOnLaunch").checked =
        getConnectOnLaunch();
});

// Debug panel
function addLogEntryToUI(entry) {
    var logEl = document.getElementById("debug-log");
    if (!logEl) return;

    var div = document.createElement("div");
    div.className = "log-entry level-" + entry.level;

    var ts = document.createElement("span");
    ts.className = "ts";
    ts.textContent = entry.timestamp + " ";

    var msg = document.createElement("span");
    msg.className = "msg";
    msg.textContent = entry.message;

    div.appendChild(ts);
    div.appendChild(msg);
    logEl.appendChild(div);

    var countEl = document.getElementById("debug-count");
    if (countEl) countEl.textContent = logger.getEntries().length;

    var nearBottom = logEl.scrollTop + logEl.clientHeight >= logEl.scrollHeight - 40;
    if (nearBottom) {
        div.scrollIntoView({ block: "end" });
    }
}

var debugExpanded = true;
document.getElementById("debug-toggle").classList.add("expanded");

document.getElementById("debug-header").addEventListener("pointerup", function () {
    debugExpanded = !debugExpanded;
    document.getElementById("debug-log").style.display = debugExpanded ? "block" : "none";
    document.getElementById("log-file-path").style.display = debugExpanded ? "block" : "none";
    if (debugExpanded) {
        document.getElementById("debug-toggle").classList.add("expanded");
    } else {
        document.getElementById("debug-toggle").classList.remove("expanded");
    }
});

document.getElementById("btnClearLog").addEventListener("pointerup", function (e) {
    e.stopPropagation();
    logger.clear();
    document.getElementById("debug-log").innerHTML = "";
    document.getElementById("debug-count").textContent = "0";
});

logger.setUICallback(addLogEntryToUI);

window.addEventListener("load", (event) => {
    logger.init().then(function () {
        logger.info("Plugin loaded");
        var pathEl = document.getElementById("log-file-path");
        if (pathEl && logger.logFilePath) {
            pathEl.textContent = "Log file: " + logger.logFilePath;
        }
    });

    if (getConnectOnLaunch()) {
        connectToServer();
    }
});
