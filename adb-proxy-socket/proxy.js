#!/usr/bin/env node

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

const express = require("express");
const http = require("http");
const { Server } = require("socket.io");
const crypto = require("crypto");
const fs = require("fs");
const path = require("path");
const os = require("os");
const app = express();
const server = http.createServer(app);

const MAX_CONNECTIONS_PER_IP = 10;
const RATE_LIMIT_MESSAGES_PER_SEC = 30;
const RATE_LIMIT_WINDOW_MS = 1000;
const MAX_REGISTER_PER_MIN = 5;

// Generate a fresh random token on each proxy startup
const AUTH_TOKEN = crypto.randomBytes(32).toString("hex");
const TOKEN_DIR = path.join(os.homedir(), ".adb-mcp");
const TOKEN_FILE = path.join(TOKEN_DIR, "token");

try {
    fs.mkdirSync(TOKEN_DIR, { recursive: true });
    fs.writeFileSync(TOKEN_FILE, AUTH_TOKEN, { mode: 0o600 });
    console.log(`[${new Date().toISOString()}] Auth token written to ${TOKEN_FILE}`);
} catch (err) {
    console.error(`[ERROR] Could not write auth token to disk: ${err.message}`);
}

// Serve token over HTTP for UXP plugins (localhost-only due to server bind below)
app.get("/__token", (_req, res) => {
    res.type("text/plain").send(AUTH_TOKEN);
});

const io = new Server(server, {
    transports: ["websocket", "polling"],
    maxHttpBufferSize: 5 * 1024 * 1024,
    pingTimeout: 60000,
    pingInterval: 25000,
    cors: { origin: /^http:\/\/localhost(:\d+)?$/ },
});

const PORT = parseInt(process.env.ADB_MCP_PROXY_PORT || "3001", 10);
// Track clients by application
const applicationClients = {};
// Track connection counts by IP for connection limiting
const connectionsByIp = {};

// Simple token-bucket rate limiter per socket
function createRateLimiter(maxPerWindow, windowMs) {
    let tokens = maxPerWindow;
    let lastRefill = Date.now();
    return function allowRequest() {
        const now = Date.now();
        const elapsed = now - lastRefill;
        if (elapsed >= windowMs) {
            tokens = maxPerWindow;
            lastRefill = now;
        }
        if (tokens > 0) {
            tokens--;
            return true;
        }
        return false;
    };
}

// Reject Socket.IO connections that don't present the correct auth token
io.use((socket, next) => {
    const token = socket.handshake.auth && socket.handshake.auth.token;
    if (!token || !crypto.timingSafeEqual(
        Buffer.from(token),
        Buffer.from(AUTH_TOKEN)
    )) {
        console.log(`[WARN] Rejected unauthenticated connection from ${socket.handshake.address}`);
        return next(new Error("Unauthorized"));
    }
    next();
});

io.on("connection", (socket) => {
    const clientIp = socket.handshake.address;

    // Enforce per-IP connection limit
    connectionsByIp[clientIp] = (connectionsByIp[clientIp] || 0) + 1;
    if (connectionsByIp[clientIp] > MAX_CONNECTIONS_PER_IP) {
        console.log(`[WARN] Connection limit exceeded for IP ${clientIp}. Disconnecting ${socket.id}.`);
        socket.disconnect(true);
        connectionsByIp[clientIp]--;
        return;
    }

    const messageRateLimiter = createRateLimiter(RATE_LIMIT_MESSAGES_PER_SEC, RATE_LIMIT_WINDOW_MS);
    const registerRateLimiter = createRateLimiter(MAX_REGISTER_PER_MIN, 60000);

    console.log(`[${new Date().toISOString()}] User connected: ${socket.id} from ${clientIp}`);

    socket.on("register", ({ application }) => {
        if (!registerRateLimiter()) {
            console.log(`[WARN] Register rate limit hit for ${socket.id}. Ignoring.`);
            return;
        }
        console.log(
            `Client ${socket.id} registered for application: ${application}`
        );

        // Store the application preference with this socket
        socket.data.application = application;

        // Register this client for this application
        if (!applicationClients[application]) {
            applicationClients[application] = new Set();
        }
        applicationClients[application].add(socket.id);

        // Optionally confirm registration
        socket.emit("registration_response", {
            type: "registration",
            status: "success",
            message: `Registered for ${application}`,
        });
    });

    socket.on("command_packet_response", ({ packet }) => {
        const senderId = packet.senderId;

        if (senderId) {
            io.to(senderId).emit("packet_response", packet);
            console.log(`Sent confirmation to client ${senderId}`);
        } else {
            console.log(`No sender ID provided in packet`);
        }
    });

    socket.on("command_packet", ({ application, command }) => {
        if (!messageRateLimiter()) {
            console.log(`[WARN] Message rate limit hit for ${socket.id}. Dropping packet.`);
            socket.emit("packet_response", {
                senderId: socket.id,
                status: "FAILURE",
                message: "Rate limit exceeded. Please slow down."
            });
            return;
        }
        console.log(
            `Command from ${socket.id} for application ${application}:`,
            command
        );

        // Register this client for this application if not already registered
        //if (!applicationClients[application]) {
        //  applicationClients[application] = new Set();
        //}
        //applicationClients[application].add(socket.id);

        // Process the command

        let packet = {
            senderId: socket.id,
            application: application,
            command: command,
        };

        sendToApplication(packet);

        // Send response back to this client
        //socket.emit('json_response', { from: 'server', command });
    });

    socket.on("disconnect", () => {
        console.log(`[${new Date().toISOString()}] User disconnected: ${socket.id}`);

        // Release connection slot for this IP
        if (connectionsByIp[clientIp] > 0) {
            connectionsByIp[clientIp]--;
        }
        if (connectionsByIp[clientIp] === 0) {
            delete connectionsByIp[clientIp];
        }

        // Remove this client from all application registrations
        for (const app in applicationClients) {
            applicationClients[app].delete(socket.id);
            // Clean up empty sets
            if (applicationClients[app].size === 0) {
                delete applicationClients[app];
            }
        }
    });
});

// Add a function to send messages to clients by application
function sendToApplication(packet) {
    let application = packet.application;
    if (applicationClients[application]) {
        console.log(
            `Sending to ${applicationClients[application].size} clients for ${application}`
        );

        let senderId = packet.senderId;
        // Loop through all client IDs for this application
        applicationClients[application].forEach((clientId) => {
            io.to(clientId).emit("command_packet", packet);
        });
        return true;
    }
    console.log(`No clients registered for application: ${application}`);
    return false;
}

// Example: Use this function elsewhere in your code
// sendToApplication('photoshop', { message: 'Update available' });

server.listen(PORT, "127.0.0.1", () => {
    console.log(
        `adb-mcp Command proxy server running on ws://localhost:${PORT}`
    );
});
