import crypto from 'node:crypto';
import zlib from 'node:zlib';

import { CONFIG } from '../config';

const PKCS8_PREFIX = Buffer.from('302e020100300506032b656e04220420', 'hex');
const SPKI_PREFIX = Buffer.from('302a300506032b656e032100', 'hex');

export function b64e(value: Buffer | string): string {
  return (Buffer.isBuffer(value) ? value : Buffer.from(value)).toString(
    'base64',
  );
}

export function b64d(value: string): Buffer {
  return Buffer.from(value, 'base64');
}

export const SERVER_PRIVATE = crypto.createPrivateKey({
  key: Buffer.concat([PKCS8_PREFIX, b64d(CONFIG.keys.private_b64)]),
  format: 'der',
  type: 'pkcs8',
});

export const SERVER_PUBLIC_B64 = CONFIG.keys.public_b64;

export function clientPublicKey(publicB64: string): crypto.KeyObject {
  return crypto.createPublicKey({
    key: Buffer.concat([SPKI_PREFIX, b64d(publicB64)]),
    format: 'der',
    type: 'spki',
  });
}

export function sharedSecret(publicB64: string): Buffer {
  return crypto.diffieHellman({
    privateKey: SERVER_PRIVATE,
    publicKey: clientPublicKey(publicB64),
  });
}

export function sha256(parts: Buffer[]): Buffer {
  const hash = crypto.createHash('sha256');
  for (const part of parts) hash.update(part);
  return hash.digest();
}

export function randomBytes(size: number): Buffer {
  return crypto.randomBytes(size);
}

export function decodeMessage(raw: Buffer | ArrayBuffer | string): unknown {
  let buffer: Buffer;
  if (typeof raw === 'string') {
    buffer = Buffer.from(raw);
  } else if (Buffer.isBuffer(raw)) {
    buffer = raw;
  } else {
    buffer = Buffer.from(raw);
  }
  try {
    buffer = zlib.gunzipSync(buffer);
  } catch {
    // The client only gzips large payloads; plain JSON is the common case.
  }
  return JSON.parse(buffer.toString('utf8'));
}

export function encodeResponse(response: Record<string, unknown>): string {
  return JSON.stringify({ r: response });
}
