import zlib from 'node:zlib';

import { CONFIG } from '../config';
import type { Account } from '../db/repositories';
import type { CommunityRow } from '../db/schema';
import {
  coverLinkForHex,
  downloadUrl,
  hexFromLink,
  linkForHex,
  writeBlob,
} from '../http/blobs';

function pngChunk(type: string, data: Buffer): Buffer {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length, 0);
  const typeBuffer = Buffer.from(type, 'ascii');
  const crc = Buffer.alloc(4);
  crc.writeUInt32BE(zlib.crc32(Buffer.concat([typeBuffer, data])) >>> 0, 0);
  return Buffer.concat([length, typeBuffer, data, crc]);
}

function encodePng(width: number, height: number, pixels: Buffer): Buffer {
  const signature = Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]);
  const ihdr = Buffer.alloc(13);
  ihdr.writeUInt32BE(width, 0);
  ihdr.writeUInt32BE(height, 4);
  ihdr[8] = 8;
  ihdr[9] = 2;
  const stride = width * 3;
  const raw = Buffer.alloc((stride + 1) * height);
  for (let y = 0; y < height; y += 1) {
    pixels.copy(raw, y * (stride + 1) + 1, y * stride, (y + 1) * stride);
  }
  return Buffer.concat([
    signature,
    pngChunk('IHDR', ihdr),
    pngChunk('IDAT', zlib.deflateSync(raw, { level: 9 })),
    pngChunk('IEND', Buffer.alloc(0)),
  ]);
}

function hueFromSeed(seed: string): number {
  let hash = 2166136261;
  for (let index = 0; index < seed.length; index += 1) {
    hash ^= seed.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0) % 360;
}

function hslToRgb(
  hue: number,
  saturation: number,
  lightness: number,
): [number, number, number] {
  const c = (1 - Math.abs(2 * lightness - 1)) * saturation;
  const hp = (((hue % 360) + 360) % 360) / 60;
  const x = c * (1 - Math.abs((hp % 2) - 1));
  let rgb: [number, number, number];
  if (hp < 1) rgb = [c, x, 0];
  else if (hp < 2) rgb = [x, c, 0];
  else if (hp < 3) rgb = [0, c, x];
  else if (hp < 4) rgb = [0, x, c];
  else if (hp < 5) rgb = [x, 0, c];
  else rgb = [c, 0, x];
  const m = lightness - c / 2;
  return [
    Math.round((rgb[0] + m) * 255),
    Math.round((rgb[1] + m) * 255),
    Math.round((rgb[2] + m) * 255),
  ];
}

function circleCoverage(
  px: number,
  py: number,
  cx: number,
  cy: number,
  radius: number,
): number {
  const distance = Math.hypot(px - cx, py - cy);
  return Math.max(0, Math.min(1, radius - distance + 0.5));
}

function renderAvatar(seed: string): Buffer {
  const size = 256;
  const hue = hueFromSeed(seed);
  const [br, bg, bb] = hslToRgb(hue, 0.42, 0.52);
  const pixels = Buffer.alloc(size * size * 3);
  const headX = size / 2;
  const headY = size * 0.41;
  const headR = size * 0.19;
  const bodyX = size / 2;
  const bodyY = size * 1.04;
  const bodyR = size * 0.4;
  for (let y = 0; y < size; y += 1) {
    for (let x = 0; x < size; x += 1) {
      const cover = Math.max(
        circleCoverage(x + 0.5, y + 0.5, headX, headY, headR),
        circleCoverage(x + 0.5, y + 0.5, bodyX, bodyY, bodyR),
      );
      const index = (y * size + x) * 3;
      pixels[index] = Math.round(br + (255 - br) * cover);
      pixels[index + 1] = Math.round(bg + (255 - bg) * cover);
      pixels[index + 2] = Math.round(bb + (255 - bb) * cover);
    }
  }
  return encodePng(size, size, pixels);
}

function renderCover(seed: string): Buffer {
  const width = 1080;
  const height = 480;
  const hue = hueFromSeed(seed);
  const top = hslToRgb(hue, 0.5, 0.44);
  const bottom = hslToRgb(hue + 45, 0.55, 0.2);
  const pixels = Buffer.alloc(width * height * 3);
  for (let y = 0; y < height; y += 1) {
    const t = y / (height - 1);
    const r = Math.round(top[0] + (bottom[0] - top[0]) * t);
    const g = Math.round(top[1] + (bottom[1] - top[1]) * t);
    const b = Math.round(top[2] + (bottom[2] - top[2]) * t);
    for (let x = 0; x < width; x += 1) {
      const index = (y * width + x) * 3;
      pixels[index] = r;
      pixels[index + 1] = g;
      pixels[index + 2] = b;
    }
  }
  return encodePng(width, height, pixels);
}

const cache = new Map<string, string>();

function storeBlob(data: Buffer, kind: 'avatar' | 'cover'): string {
  const hex = writeBlob(data);
  return kind === 'cover' ? coverLinkForHex(hex) : linkForHex(hex);
}

function generatedAvatarLink(seed: string): string {
  const key = `avatar:${seed}`;
  let link = cache.get(key);
  if (!link) {
    link = storeBlob(renderAvatar(seed), 'avatar');
    cache.set(key, link);
  }
  return link;
}

function generatedCoverLink(seed: string): string {
  const key = `cover:${seed}`;
  let link = cache.get(key);
  if (!link) {
    link = storeBlob(renderCover(seed), 'cover');
    cache.set(key, link);
  }
  return link;
}

function resolveAvatarLink(custom: string, seed: string): string {
  return custom || generatedAvatarLink(seed);
}

function resolveCoverLink(custom: string, seed: string): string {
  return custom || generatedCoverLink(seed);
}

export function accountAvatarLink(account: Account): string {
  return resolveAvatarLink(account.avatarUrl, `account:${account.accountId}`);
}

export function accountCoverLink(account: Account): string {
  return resolveCoverLink(
    account.backgroundUrl,
    `account:${account.accountId}`,
  );
}

export function accountAvatarHttp(account: Account): string {
  const hex = hexFromLink(accountAvatarLink(account));
  return hex ? downloadUrl(hex) : CONFIG.avatarHttpUrl;
}

export function communityAvatarLink(community: CommunityRow): string {
  return resolveAvatarLink(community.icon, `community:${community.communityId}`);
}

export function communityCoverLink(community: CommunityRow): string {
  return resolveCoverLink(
    community.cover,
    `community:${community.communityId}`,
  );
}
