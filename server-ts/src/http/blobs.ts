import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { CONFIG } from '../config';

const DIR = path.join(CONFIG.serverDir, 'blobs');

function ensureDir(): void {
  fs.mkdirSync(DIR, { recursive: true });
}

function urlSafeFromB64(value: string): string {
  return value.replaceAll('/', '_').replaceAll('+', '-').replaceAll('=', '.');
}

function b64FromUrlSafe(value: string): string {
  return value.replaceAll('_', '/').replaceAll('-', '+').replaceAll('.', '=');
}

export function linkFromHashB64(hashB64: string): string {
  return `longdan://avatar/${urlSafeFromB64(hashB64)}`;
}

export function linkForHex(hex: string): string {
  return linkFromHashB64(Buffer.from(hex, 'hex').toString('base64'));
}

export function hexFromHashB64(hashB64: string): string | null {
  try {
    const bytes = Buffer.from(hashB64, 'base64');
    if (bytes.length !== 16) return null;
    return bytes.toString('hex');
  } catch {
    return null;
  }
}

export function hexFromSegment(segment: string): string | null {
  if (/^[0-9a-fA-F]{32}$/.test(segment)) return segment.toLowerCase();
  try {
    const decoded = Buffer.from(b64FromUrlSafe(segment), 'base64');
    if (decoded.length === 16) return decoded.toString('hex');
    const asText = decoded.toString('utf8');
    if (asText.startsWith('longdan://')) {
      const inner = asText.slice(asText.lastIndexOf('/') + 1);
      if (/^[0-9a-fA-F]{32}$/.test(inner)) return inner.toLowerCase();
      const innerDecoded = Buffer.from(b64FromUrlSafe(inner), 'base64');
      if (innerDecoded.length === 16) return innerDecoded.toString('hex');
    }
  } catch {
    /* ignore invalid segments */
  }
  return null;
}

export function hexFromLink(link: string): string | null {
  if (typeof link !== 'string' || link.length === 0) return null;
  const segment = link.slice(link.lastIndexOf('/') + 1);
  return hexFromSegment(segment);
}

export function blobPath(hex: string): string {
  return path.join(DIR, hex);
}

export function hasBlob(hex: string): boolean {
  return /^[0-9a-f]{32}$/.test(hex) && fs.existsSync(blobPath(hex));
}

export function writeBlob(data: Buffer): string {
  const hex = crypto.createHash('md5').update(data).digest('hex');
  ensureDir();
  fs.writeFileSync(blobPath(hex), data);
  return hex;
}

export function readBlob(hex: string): Buffer | null {
  if (!hasBlob(hex)) return null;
  return fs.readFileSync(blobPath(hex));
}

export function downloadUrl(hex: string): string {
  return `${CONFIG.blobBase}${hex}`;
}
