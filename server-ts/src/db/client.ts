import Database from 'better-sqlite3';
import { drizzle } from 'drizzle-orm/better-sqlite3';
import { CONFIG } from '../config';
import * as schema from './schema';
import { SCHEMA_SQL } from './schema-sql';

export const sqlite = new Database(CONFIG.dbPath);
sqlite.pragma('journal_mode = WAL');
sqlite.pragma('foreign_keys = ON');
sqlite.pragma('busy_timeout = 10000');

export const db = drizzle(sqlite, { schema });

export function initializeDatabase(): void {
  sqlite.exec(SCHEMA_SQL);
  const accountColumns = sqlite
    .prepare('PRAGMA table_info(accounts)')
    .all()
    .map((column) => (column as { name: string }).name);
  if (!accountColumns.includes('bio')) {
    sqlite.exec("ALTER TABLE accounts ADD COLUMN bio TEXT NOT NULL DEFAULT ''");
  }
  if (!accountColumns.includes('avatar_url')) {
    sqlite.exec("ALTER TABLE accounts ADD COLUMN avatar_url TEXT NOT NULL DEFAULT ''");
  }
  if (!accountColumns.includes('background_url')) {
    sqlite.exec("ALTER TABLE accounts ADD COLUMN background_url TEXT NOT NULL DEFAULT ''");
  }
  if (!accountColumns.includes('info_images')) {
    sqlite.exec("ALTER TABLE accounts ADD COLUMN info_images TEXT NOT NULL DEFAULT '[]'");
  }
  if (!accountColumns.includes('decoration_json')) {
    sqlite.exec("ALTER TABLE accounts ADD COLUMN decoration_json TEXT NOT NULL DEFAULT ''");
  }
  sqlite.pragma('user_version = 1');

  try {
    sqlite.exec(
      'CREATE UNIQUE INDEX IF NOT EXISTS accounts_omlet_id_unique ON accounts(omlet_id COLLATE NOCASE)',
    );
  } catch (error) {
    console.warn(
      '[db] não foi possível criar o índice único de omlet_id',
      error,
    );
  }
}
