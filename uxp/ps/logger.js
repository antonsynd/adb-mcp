const fs = require('fs');

const MAX_UI_ENTRIES = 500;

let logDir = null;
let logFilePath = null;
let fileLoggingEnabled = false;
let entries = [];
let uiCallback = null;

function resolveHome() {
    try {
        var os = require('os');
        if (os.homedir) return os.homedir();
    } catch {}
    try {
        if (typeof process !== 'undefined' && process.env && process.env.HOME) return process.env.HOME;
    } catch {}
    return '/Users/' + (typeof process !== 'undefined' && process.env && process.env.USER ? process.env.USER : 'shared');
}

async function init() {
    try {
        var home = resolveHome();
        logDir = home + '/Documents/adb-mcp-logs';
        logFilePath = logDir + '/photoshop-mcp.log';

        try {
            await fs.lstat(logDir);
        } catch {
            await fs.mkdir(logDir);
        }

        fileLoggingEnabled = true;

        var sep = '='.repeat(60);
        await appendToFile('\n' + sep + '\n' + 'Session started: ' + new Date().toISOString() + '\n' + sep + '\n');
        console.log('Logger file init OK: ' + logFilePath);
    } catch (e) {
        console.error('Logger file init failed:', e);
        fileLoggingEnabled = false;
    }
}

async function appendToFile(text) {
    if (!fileLoggingEnabled) return;
    try {
        var existing = '';
        try { existing = await fs.readFile(logFilePath, 'utf-8'); } catch {}
        await fs.writeFile(logFilePath, existing + text, 'utf-8');
    } catch (e) {
        fileLoggingEnabled = false;
        console.error('File logging disabled due to error:', e);
    }
}

function formatArgs(args) {
    return args
        .map((a) => {
            if (a instanceof Error) return a.message + (a.stack ? '\n' + a.stack : '');
            if (typeof a === 'object') {
                try { return JSON.stringify(a, null, 2); } catch { return String(a); }
            }
            return String(a);
        })
        .join(' ');
}

function log(level, args) {
    const message = formatArgs(args);
    const now = new Date();
    const timestamp = now.toISOString().slice(11, 23);
    const fullTimestamp = now.toISOString();

    const entry = { timestamp, level, message };
    entries.push(entry);
    if (entries.length > MAX_UI_ENTRIES) entries.shift();

    if (uiCallback) {
        try { uiCallback(entry); } catch {}
    }

    appendToFile('[' + fullTimestamp + '] [' + level.toUpperCase().padEnd(5) + '] ' + message + '\n');

    const fn = level === 'error' ? 'error' : level === 'warn' ? 'warn' : 'log';
    console[fn]('[' + level + ']', ...args);
}

module.exports = {
    init,
    info: function () { log('info', Array.from(arguments)); },
    warn: function () { log('warn', Array.from(arguments)); },
    error: function () { log('error', Array.from(arguments)); },
    debug: function () { log('debug', Array.from(arguments)); },
    hint: function () { log('hint', Array.from(arguments)); },
    getEntries: function () { return entries; },
    clear: function () { entries.length = 0; },
    setUICallback: function (cb) { uiCallback = cb; },
    get logFilePath() { return logFilePath; },
};
