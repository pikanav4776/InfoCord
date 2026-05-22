// crypto.js — InfoCord client-side encryption
// All encryption/decryption happens here. The server never sees plaintext.

const PBKDF2_ITERATIONS = 310_000;

// ── Key derivation ──────────────────────────────────────────────────────────

async function deriveKey(password, salt) {
  const enc = new TextEncoder();
  const keyMaterial = await crypto.subtle.importKey(
    "raw",
    enc.encode(password),
    { name: "PBKDF2" },
    false,
    ["deriveKey"]
  );
  return crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: salt,
      iterations: PBKDF2_ITERATIONS,
      hash: "SHA-256",
    },
    keyMaterial,
    { name: "AES-GCM", length: 256 },
    false,        // non-extractable — key bytes can never be read back out
    ["encrypt", "decrypt"]
  );
}

// ── Encrypt ─────────────────────────────────────────────────────────────────

async function encryptNote(plaintext, password) {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const iv   = crypto.getRandomValues(new Uint8Array(12));
  const key  = await deriveKey(password, salt);

  const ciphertext = await crypto.subtle.encrypt(
    { name: "AES-GCM", iv: iv },
    key,
    new TextEncoder().encode(plaintext)
  );

  return {
    ciphertext: bufToBase64(ciphertext),
    iv:         bufToBase64(iv),
    salt:       bufToBase64(salt),
  };
}

// ── Decrypt ─────────────────────────────────────────────────────────────────

async function decryptNote({ ciphertext, iv, salt }, password) {
  const key = await deriveKey(password, base64ToBuf(salt));

  const plaintext = await crypto.subtle.decrypt(
    { name: "AES-GCM", iv: base64ToBuf(iv) },
    key,
    base64ToBuf(ciphertext)
  );

  return new TextDecoder().decode(plaintext);
}

// ── Session key cache ────────────────────────────────────────────────────────
// Holds the password in memory for the duration of the session only.
// Never written to localStorage, sessionStorage, or cookies.

let _sessionPassword = null;

function setSessionPassword(password) { _sessionPassword = password; }
function getSessionPassword()         { return _sessionPassword; }
function clearSessionPassword()       { _sessionPassword = null; }

// ── Helpers ──────────────────────────────────────────────────────────────────

function bufToBase64(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)));
}

function base64ToBuf(b64) {
  return Uint8Array.from(atob(b64), c => c.charCodeAt(0));
}