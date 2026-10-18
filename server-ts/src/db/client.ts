import Database from 'better-sqlite3';
import { drizzle } from 'drizzle-orm/better-sqlite3';
import { CONFIG } from '../config';
import * as schema from './schema';
import { SCHEMA_SQL } from './schema-sql';
import { accounts, channels, communities, communityMembers, posts } from './schema';

export const sqlite = new Database(CONFIG.dbPath);
sqlite.pragma('journal_mode = WAL');
sqlite.pragma('foreign_keys = ON');
sqlite.pragma('busy_timeout = 10000');

export const db = drizzle(sqlite, { schema });

function now(): number {
  return Date.now();
}

export function initializeDatabase(): void {
  sqlite.exec(SCHEMA_SQL);
  sqlite.pragma('user_version = 1');

  const firstAccount = db
    .select()
    .from(accounts)
    .orderBy(accounts.createdMs)
    .limit(1)
    .get();

  const communityCount =
    db.select({ value: schema.communities.communityId }).from(communities).all()
      .length;
  if (communityCount === 0) {
    db.insert(communities)
      .values({
        communityId: CONFIG.localCommunityId,
        name: 'Comunidade Local',
        description: 'Comunidade local de testes',
        icon: CONFIG.avatarBlobUrl,
        cover: CONFIG.coverBlobUrl,
        ownerAccountId: firstAccount?.accountId ?? null,
        createdMs: now(),
      })
      .run();
    if (firstAccount) {
      db.insert(communityMembers)
        .values({
          communityId: CONFIG.localCommunityId,
          accountId: firstAccount.accountId,
          role: 'owner',
          joinedMs: now(),
        })
        .onConflictDoNothing()
        .run();
    }
  }

  const channelCount =
    db.select({ value: channels.channelId }).from(channels).all().length;
  if (channelCount === 0) {
    db.insert(channels)
      .values({
        channelId: CONFIG.localChannelId,
        communityId: CONFIG.localCommunityId,
        name: 'geral',
        description: 'Canal de texto da comunidade',
        keyB64: CONFIG.localChannelKey,
        createdMs: now(),
      })
      .run();
  }

  const postCount = db.select({ value: posts.postId }).from(posts).all().length;
  if (postCount === 0 && firstAccount) {
    db.insert(posts)
      .values({
        postId: 'local-post-1',
        authorAccountId: firstAccount.accountId,
        title: CONFIG.seedTitle,
        description: CONFIG.seedDescription,
        createdMs: now(),
      })
      .onConflictDoNothing()
      .run();
  }
}
