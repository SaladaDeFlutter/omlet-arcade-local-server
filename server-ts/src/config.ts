import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(__dirname, '..');
const PROJECT = path.resolve(ROOT, '..');

function envInt(name: string, fallback: number): number {
  const value = Number(process.env[name]);
  return Number.isFinite(value) && value > 0 ? value : fallback;
}

export const CONFIG = (() => {
  const serverDir = process.env.OMLET_SERVER_DIR
    ? path.resolve(process.env.OMLET_SERVER_DIR)
    : path.join(PROJECT, 'server');
  const keysPath = process.env.OMLET_KEYS_PATH
    ? path.resolve(process.env.OMLET_KEYS_PATH)
    : path.join(serverDir, 'keys.json');
  const keys = JSON.parse(fs.readFileSync(keysPath, 'utf8')) as {
    private_b64: string;
    public_b64: string;
  };
  const publicHost = process.env.PUBLIC_HOST ?? '192.168.240.1';
  const avatarPath = process.env.OMLET_AVATAR_PATH
    ? path.resolve(process.env.OMLET_AVATAR_PATH)
    : path.join(serverDir, 'avatar.png');
  const coverPath = process.env.OMLET_COVER_PATH
    ? path.resolve(process.env.OMLET_COVER_PATH)
    : path.join(serverDir, 'cover.png');

  function fileBlobUrl(name: string, filePath: string): string {
    if (!fs.existsSync(filePath)) return '';
    const digest = crypto
      .createHash('md5')
      .update(fs.readFileSync(filePath))
      .digest();
    const encoded = digest
      .toString('base64')
      .replaceAll('/', '_')
      .replaceAll('+', '-')
      .replaceAll('=', '.');
    return `longdan://${name}/${encoded}`;
  }

  return {
    root: ROOT,
    serverDir,
    keysPath,
    keys,
    dbPath: process.env.OMLET_DB_PATH
      ? path.resolve(process.env.OMLET_DB_PATH)
      : path.join(serverDir, 'omlet.db'),
    publicHost,
    port: envInt('OMLET_PORT', 8080),
    assetPort: envInt('OMLET_ASSET_PORT', 8081),
    avatarPath,
    coverPath,
    avatarHttpUrl: `http://${publicHost}:${envInt('OMLET_ASSET_PORT', 8081)}/avatar.png`,
    coverHttpUrl: `http://${publicHost}:${envInt('OMLET_ASSET_PORT', 8081)}/cover.png`,
    blobBase: `http://${publicHost}:${envInt('OMLET_ASSET_PORT', 8081)}/blob/`,
    avatarBlobUrl: fileBlobUrl('avatar', avatarPath),
    coverBlobUrl: fileBlobUrl('cover', coverPath),
    localCommunityId: 'local-community',
    localChannelId: 'local-community-general',
    localChannelKey: Buffer.from('omlet-local-channel').toString('base64'),
    seedTitle: 'Hello from the local Omlet server!',
    seedDescription: 'Posted via the local server',
  };
})();
