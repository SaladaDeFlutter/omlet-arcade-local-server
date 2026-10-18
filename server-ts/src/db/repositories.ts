import crypto from 'node:crypto';
import { and, desc, eq, sql } from 'drizzle-orm';

import { CONFIG } from '../config';
import { db } from './client';
import {
  accounts,
  channelMessages,
  channels,
  comments,
  communities,
  communityMembers,
  postLikes,
  posts,
  type AccountRow,
  type ChannelMessageRow,
  type ChannelRow,
  type CommentRow,
  type CommunityRow,
  type PostRow,
} from './schema';

export interface Account {
  accountId: string;
  clientPub: string | null;
  omletId: string;
  scopes: string[];
  createdMs: number;
  hasEmail: boolean;
  hasPassword: boolean;
  z: Record<string, unknown>;
  bio: string;
  avatarUrl: string;
  backgroundUrl: string;
  infoImages: string[];
  decorationJson: string;
}

export interface AccountInput {
  accountId: string;
  clientPub?: string | null;
  omletId: string;
  scopes: string[];
  createdMs: number;
  hasEmail?: boolean;
  hasPassword?: boolean;
  z: Record<string, unknown>;
  bio?: string;
  avatarUrl?: string;
  backgroundUrl?: string;
  infoImages?: string[];
  decorationJson?: string;
}

export interface PostWithAuthor {
  post: PostRow;
  author: Account;
}

export interface CommentWithAuthor {
  comment: CommentRow;
  author: Account;
}

export interface MemberWithAccount {
  role: string;
  joinedMs: number;
  account: Account;
}

export interface MessageWithAuthor {
  message: ChannelMessageRow;
  author: Account;
}

function now(): number {
  return Date.now();
}

function b64(bytes: Buffer): string {
  return bytes.toString('base64');
}

export function randomId(bytes = 16): string {
  return crypto.randomBytes(bytes).toString('hex');
}

function parseInfoImages(raw: string | null): string[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((item): item is string => typeof item === 'string')
      : [];
  } catch {
    return [];
  }
}

function parseAccount(row: AccountRow): Account {
  let z: Record<string, unknown> = {};
  try {
    z = JSON.parse(row.accountJson) as Record<string, unknown>;
  } catch {
    z = {};
  }
  let scopes: string[] = [];
  try {
    const parsed = JSON.parse(row.scopesJson);
    if (Array.isArray(parsed)) scopes = parsed.map(String);
  } catch {
    scopes = [];
  }
  return {
    accountId: row.accountId,
    clientPub: row.clientPub ?? null,
    omletId: row.omletId,
    scopes,
    createdMs: row.createdMs,
    hasEmail: Boolean(row.hasEmail),
    hasPassword: Boolean(row.hasPassword),
    z,
    bio: row.bio ?? '',
    avatarUrl: row.avatarUrl ?? '',
    backgroundUrl: row.backgroundUrl ?? '',
    infoImages: parseInfoImages(row.infoImages),
    decorationJson: row.decorationJson ?? '',
  };
}

export class Repositories {
  findAccount(accountId?: string, clientPub?: string): Account | null {
    let row: AccountRow | undefined;
    if (accountId) {
      row = db
        .select()
        .from(accounts)
        .where(eq(accounts.accountId, accountId))
        .get();
    }
    if (!row && clientPub) {
      row = db
        .select()
        .from(accounts)
        .where(eq(accounts.clientPub, clientPub))
        .get();
    }
    return row ? parseAccount(row) : null;
  }

  findAccountByOmletId(omletId: string): Account | null {
    const name = omletId.trim();
    if (!name) return null;
    const row = db
      .select()
      .from(accounts)
      .where(sql`lower(${accounts.omletId}) = lower(${name})`)
      .get();
    return row ? parseAccount(row) : null;
  }

  isOmletIdAvailable(omletId: string, exceptClientPub?: string): boolean {
    const clash = this.findAccountByOmletId(omletId);
    if (!clash) return true;
    return Boolean(
      exceptClientPub && clash.clientPub && clash.clientPub === exceptClientPub,
    );
  }

  uniqueGuestOmletId(base = 'omletplayer'): string {
    if (this.isOmletIdAvailable(base)) return base;
    for (let attempt = 0; attempt < 100; attempt += 1) {
      const candidate = `${base}${crypto.randomInt(1000, 10000)}`;
      if (this.isOmletIdAvailable(candidate)) return candidate;
    }
    return `${base}${Date.now()}`;
  }

  upsertAccount(input: AccountInput): Account {
    const existing =
      this.findAccount(input.accountId, input.clientPub ?? undefined) ?? null;
    const values = {
      accountId: input.accountId,
      clientPub: input.clientPub || null,
      omletId: input.omletId,
      scopesJson: JSON.stringify(input.scopes),
      createdMs: input.createdMs,
      hasEmail: input.hasEmail === false ? 0 : 1,
      hasPassword: input.hasPassword === false ? 0 : 1,
      accountJson: JSON.stringify(input.z ?? {}),
      bio: input.bio ?? '',
      avatarUrl: input.avatarUrl ?? '',
      backgroundUrl: input.backgroundUrl ?? '',
      infoImages: JSON.stringify(input.infoImages ?? []),
      decorationJson: input.decorationJson ?? '',
    };
    if (existing) {
      db.update(accounts)
        .set(values)
        .where(eq(accounts.accountId, existing.accountId))
        .run();
    } else {
      db.insert(accounts).values(values).run();
    }
    const result = this.findAccount(values.accountId);
    if (!result) throw new Error('failed to upsert account');
    return result;
  }

  ensureAccount(accountId: string, omletId?: string): Account {
    const existing = this.findAccount(accountId);
    if (existing) return existing;
    const name =
      omletId && omletId.trim() ? omletId.trim() : this.uniqueGuestOmletId();
    const stamp = now();
    return this.upsertAccount({
      accountId,
      clientPub: null,
      omletId: name,
      scopes: ['PublicProfile', 'Arcade'],
      createdMs: stamp,
      hasEmail: true,
      hasPassword: true,
      z: {
        a: {
          a: accountId,
          c: 'ONE',
          d: 'GUEST',
          i: [{ p: name, t: 'omlet' }],
          p: name,
          s: stamp,
        },
        S: ['PublicProfile', 'Arcade'],
        i: b64(Buffer.alloc(0)),
        e: true,
        p: false,
      },
      bio: '',
      avatarUrl: '',
      backgroundUrl: '',
      infoImages: [],
      decorationJson: '',
    });
  }

  updateBio(accountId: string, bio: string): void {
    db.update(accounts).set({ bio }).where(eq(accounts.accountId, accountId)).run();
  }

  updateAvatarUrl(accountId: string, avatarUrl: string): void {
    db.update(accounts)
      .set({ avatarUrl })
      .where(eq(accounts.accountId, accountId))
      .run();
  }

  updateBackgroundUrl(accountId: string, backgroundUrl: string): void {
    db.update(accounts)
      .set({ backgroundUrl })
      .where(eq(accounts.accountId, accountId))
      .run();
  }

  updateInfoImages(accountId: string, infoImages: string[]): void {
    db.update(accounts)
      .set({ infoImages: JSON.stringify(infoImages) })
      .where(eq(accounts.accountId, accountId))
      .run();
  }

  updateDecoration(accountId: string, decorationJson: string): void {
    db.update(accounts)
      .set({ decorationJson })
      .where(eq(accounts.accountId, accountId))
      .run();
  }

  countAccounts(): number {
    return (
      db.select({ value: sql<number>`count(*)` }).from(accounts).get()?.value ??
      0
    );
  }

  firstAccount(): Account | null {
    const row = db
      .select()
      .from(accounts)
      .orderBy(accounts.createdMs)
      .limit(1)
      .get();
    return row ? parseAccount(row) : null;
  }

  listPosts(limit = 50): PostWithAuthor[] {
    const rows = db
      .select({ post: posts, author: accounts })
      .from(posts)
      .innerJoin(accounts, eq(posts.authorAccountId, accounts.accountId))
      .orderBy(desc(posts.createdMs))
      .limit(limit)
      .all();
    return rows.map((row) => ({
      post: row.post,
      author: parseAccount(row.author),
    }));
  }

  getPost(postId: string): PostWithAuthor | null {
    const row = db
      .select({ post: posts, author: accounts })
      .from(posts)
      .innerJoin(accounts, eq(posts.authorAccountId, accounts.accountId))
      .where(eq(posts.postId, postId))
      .get();
    return row ? { post: row.post, author: parseAccount(row.author) } : null;
  }

  ensurePost(
    postId: string,
    authorAccountId: string,
    title: string,
    description = '',
  ): PostRow {
    db.insert(posts)
      .values({
        postId,
        authorAccountId,
        title,
        description,
        createdMs: now(),
      })
      .onConflictDoNothing()
      .run();
    const row = db.select().from(posts).where(eq(posts.postId, postId)).get();
    if (!row) throw new Error('failed to create post');
    return row;
  }

  ensureSeedPost(account: Account): PostWithAuthor {
    const existing = this.listPosts(1)[0];
    if (existing) return existing;
    this.ensurePost(
      'local-post-1',
      account.accountId,
      CONFIG.seedTitle,
      CONFIG.seedDescription,
    );
    const created = this.getPost('local-post-1');
    if (!created) throw new Error('failed to seed post');
    return created;
  }

  countPostsByAuthor(accountId: string): number {
    return (
      db
        .select({ value: sql<number>`count(*)` })
        .from(posts)
        .where(eq(posts.authorAccountId, accountId))
        .get()?.value ?? 0
    );
  }

  setLike(postId: string, accountId: string, liked: boolean): number {
    if (liked) {
      db.insert(postLikes)
        .values({ postId, accountId, createdMs: now() })
        .onConflictDoNothing()
        .run();
    } else {
      db.delete(postLikes)
        .where(
          and(eq(postLikes.postId, postId), eq(postLikes.accountId, accountId)),
        )
        .run();
    }
    return this.countLikes(postId);
  }

  isLiked(postId: string, accountId: string): boolean {
    return Boolean(
      db
        .select({ postId: postLikes.postId })
        .from(postLikes)
        .where(
          and(eq(postLikes.postId, postId), eq(postLikes.accountId, accountId)),
        )
        .get(),
    );
  }

  countLikes(postId: string): number {
    const post = db.select().from(posts).where(eq(posts.postId, postId)).get();
    if (!post) return 0;
    const count =
      db
        .select({ value: sql<number>`count(*)` })
        .from(postLikes)
        .where(eq(postLikes.postId, postId))
        .get()?.value ?? 0;
    return Number(post.legacyLikeCount) + Number(count);
  }

  listComments(postId: string): CommentWithAuthor[] {
    const rows = db
      .select({ comment: comments, author: accounts })
      .from(comments)
      .innerJoin(accounts, eq(comments.authorAccountId, accounts.accountId))
      .where(eq(comments.postId, postId))
      .orderBy(comments.createdMs)
      .all();
    return rows.map((row) => ({
      comment: row.comment,
      author: parseAccount(row.author),
    }));
  }

  countComments(postId: string): number {
    return (
      db
        .select({ value: sql<number>`count(*)` })
        .from(comments)
        .where(eq(comments.postId, postId))
        .get()?.value ?? 0
    );
  }

  addComment(
    postId: string,
    authorAccountId: string,
    text: string,
    clientId?: string | null,
  ): CommentRow {
    const commentId = clientId || b64(crypto.randomBytes(8));
    db.insert(comments)
      .values({
        commentId,
        postId,
        authorAccountId,
        text,
        createdMs: now(),
        clientId: clientId ?? null,
      })
      .onConflictDoNothing()
      .run();
    const row = db
      .select()
      .from(comments)
      .where(eq(comments.commentId, commentId))
      .get();
    if (!row) throw new Error('failed to add comment');
    return row;
  }

  insertCommunity(
    communityId: string,
    name: string,
    description: string,
    icon: string,
    cover: string,
    ownerAccountId: string | null,
  ): CommunityRow {
    db.insert(communities)
      .values({
        communityId,
        name,
        description,
        icon: icon || CONFIG.avatarBlobUrl,
        cover: cover || CONFIG.coverBlobUrl,
        ownerAccountId,
        createdMs: now(),
      })
      .onConflictDoNothing()
      .run();
    const row = this.getCommunity(communityId);
    if (!row) throw new Error('failed to create community');
    return row;
  }

  createCommunity(
    name: string,
    description: string,
    icon: string,
    cover: string,
    ownerAccountId: string,
  ): CommunityRow {
    const communityId = randomId();
    const community = this.insertCommunity(
      communityId,
      name,
      description,
      icon,
      cover,
      ownerAccountId,
    );
    this.addMember(communityId, ownerAccountId, 'owner');
    return community;
  }

  getCommunity(communityId: string): CommunityRow | null {
    return (
      db
        .select()
        .from(communities)
        .where(eq(communities.communityId, communityId))
        .get() ?? null
    );
  }

  listCommunities(accountId?: string, limit = 50): CommunityRow[] {
    if (accountId) {
      const rows = db
        .select({ community: communities })
        .from(communities)
        .innerJoin(
          communityMembers,
          eq(communityMembers.communityId, communities.communityId),
        )
        .where(eq(communityMembers.accountId, accountId))
        .orderBy(desc(communities.createdMs))
        .limit(limit)
        .all();
      return rows.map((row) => row.community);
    }
    return db
      .select()
      .from(communities)
      .orderBy(desc(communities.createdMs))
      .limit(limit)
      .all();
  }

  addMember(
    communityId: string,
    accountId: string,
    role = 'member',
  ): void {
    db.insert(communityMembers)
      .values({ communityId, accountId, role, joinedMs: now() })
      .onConflictDoUpdate({
        target: [communityMembers.communityId, communityMembers.accountId],
        set: { role },
      })
      .run();
  }

  listMembers(communityId: string): MemberWithAccount[] {
    const rows = db
      .select({ member: communityMembers, account: accounts })
      .from(communityMembers)
      .innerJoin(accounts, eq(communityMembers.accountId, accounts.accountId))
      .where(eq(communityMembers.communityId, communityId))
      .orderBy(communityMembers.joinedMs)
      .all();
    return rows.map((row) => ({
      role: row.member.role,
      joinedMs: row.member.joinedMs,
      account: parseAccount(row.account),
    }));
  }

  countMembers(communityId: string): number {
    return (
      db
        .select({ value: sql<number>`count(*)` })
        .from(communityMembers)
        .where(eq(communityMembers.communityId, communityId))
        .get()?.value ?? 0
    );
  }

  insertChannel(
    channelId: string,
    communityId: string,
    name: string,
    description: string,
    keyB64?: string,
  ): ChannelRow {
    db.insert(channels)
      .values({
        channelId,
        communityId,
        name,
        description,
        keyB64: keyB64 || b64(crypto.randomBytes(16)),
        createdMs: now(),
      })
      .onConflictDoNothing()
      .run();
    const row = this.getChannel(channelId);
    if (!row) throw new Error('failed to create channel');
    return row;
  }

  createChannel(
    communityId: string,
    name = 'geral',
    description = '',
  ): ChannelRow {
    const channelId = `${communityId}-${randomId(5)}`;
    return this.insertChannel(channelId, communityId, name, description);
  }

  getChannel(channelId: string): ChannelRow | null {
    return (
      db
        .select()
        .from(channels)
        .where(eq(channels.channelId, channelId))
        .get() ?? null
    );
  }

  listChannels(communityId?: string, accountId?: string): ChannelRow[] {
    if (communityId) {
      return db
        .select()
        .from(channels)
        .where(eq(channels.communityId, communityId))
        .orderBy(channels.createdMs)
        .all();
    }
    if (accountId) {
      const rows = db
        .select({ channel: channels })
        .from(channels)
        .innerJoin(
          communityMembers,
          eq(communityMembers.communityId, channels.communityId),
        )
        .where(eq(communityMembers.accountId, accountId))
        .orderBy(channels.createdMs)
        .all();
      return rows.map((row) => row.channel);
    }
    return db.select().from(channels).orderBy(channels.createdMs).all();
  }

  addMessage(
    channelId: string,
    authorAccountId: string,
    text: string,
    messageId?: string | null,
    createdUs?: number,
    clientId?: string | null,
  ): ChannelMessageRow {
    const id = messageId || b64(crypto.randomBytes(32));
    db.insert(channelMessages)
      .values({
        messageId: id,
        channelId,
        authorAccountId,
        text,
        createdUs: createdUs ?? Date.now() * 1000,
        clientId: clientId ?? null,
      })
      .onConflictDoNothing()
      .run();
    const row = db
      .select()
      .from(channelMessages)
      .where(eq(channelMessages.messageId, id))
      .get();
    if (!row) throw new Error('failed to add message');
    return row;
  }

  listMessages(channelId: string, limit = 100): MessageWithAuthor[] {
    const rows = db
      .select({ message: channelMessages, author: accounts })
      .from(channelMessages)
      .innerJoin(
        accounts,
        eq(channelMessages.authorAccountId, accounts.accountId),
      )
      .where(eq(channelMessages.channelId, channelId))
      .orderBy(channelMessages.createdUs)
      .limit(limit)
      .all();
    return rows.map((row) => ({
      message: row.message,
      author: parseAccount(row.author),
    }));
  }

  countMessages(channelId: string): number {
    return (
      db
        .select({ value: sql<number>`count(*)` })
        .from(channelMessages)
        .where(eq(channelMessages.channelId, channelId))
        .get()?.value ?? 0
    );
  }
}

export const repositories = new Repositories();
