import { CONFIG } from '../config';
import type {
  Account,
  CommentWithAuthor,
  MessageWithAuthor,
  PostWithAuthor,
} from '../db/repositories';
import type { ChannelRow, CommunityRow } from '../db/schema';
import { repositories } from '../db/repositories';
import { b64d, b64e } from './crypto';

export function sessionZ(account: Account): Record<string, unknown> {
  const z = structuredClone(account.z) as Record<string, any>;
  z.e = account.hasEmail;
  z.p = false;
  if (z.a && typeof z.a === 'object') z.a.h = account.hasPassword;
  return z;
}

export function profileAbout(account: Account): Record<string, unknown> {
  const stamp = Date.now();
  const omletId = account.omletId;
  return {
    a: omletId,
    al: account.createdMs,
    lm: stamp,
    bg: account.backgroundUrl || CONFIG.coverBlobUrl,
    fc: {
      m: { ci: account.avatarUrl || CONFIG.avatarBlobUrl, dn: omletId },
      cci: { p: omletId, cid: omletId, ct: 'App' },
      uci: [],
      c: 0,
      p: 0,
      l: 0,
      im: false,
    },
    g: 'Unknown',
    p: [],
    s: 'Omlet Arcade guest',
    tfs: false,
    p2pfc: 0,
    p2popb: 0,
  };
}

export function profileDetail(account: Account): Record<string, unknown> {
  return {
    v: 0,
    pu: account.omletId,
    i: [{ p: account.omletId, t: 'omlet' }],
    n: account.omletId,
    p: account.avatarUrl || CONFIG.avatarBlobUrl,
    au: CONFIG.avatarHttpUrl,
  };
}

export function commentAuthor(account: Account): Record<string, unknown> {
  return {
    a: account.accountId,
    n: account.omletId,
    p: account.avatarUrl || CONFIG.avatarBlobUrl,
    vfs: [],
  };
}

export function commentSubject(
  account: Account,
  postId: string,
): Record<string, unknown> {
  return {
    a: account.accountId,
    t: 'Message',
    id: b64e(Buffer.from(postId)),
  };
}

export function communityInfo(
  community: CommunityRow,
): Record<string, unknown> {
  return {
    cid: { ct: 'Managed', cid: community.communityId, p: 'Android' },
    n: community.name,
    i: community.icon || CONFIG.avatarBlobUrl,
    ll: [],
    sq: false,
  };
}

export function communityEe(
  community: CommunityRow,
  accountId?: string,
): Record<string, unknown> {
  const members = repositories.listMembers(community.communityId);
  const admins = members
    .filter((member) => member.role === 'owner' || member.role === 'admin')
    .map((member) => member.account.accountId);
  if (
    community.ownerAccountId &&
    !admins.includes(community.ownerAccountId)
  ) {
    admins.push(community.ownerAccountId);
  }
  if (admins.length === 0 && accountId) admins.push(accountId);
  return {
    cci: {
      ct: 'Managed',
      cid: community.communityId,
      p: 'Android',
    },
    c: members.length,
    p: 0,
    l: 0,
    im: false,
    m: {
      dn: community.name,
      ci: community.icon || CONFIG.avatarBlobUrl,
      b: community.cover || CONFIG.coverBlobUrl,
      d: community.description ?? '',
      al: admins,
    },
    t: Date.now(),
  };
}

export function channelEo(channel: ChannelRow): Record<string, unknown> {
  return { a: channel.channelId, k: channel.keyB64 };
}

export function channelIo(
  channel: ChannelRow,
  community: CommunityRow,
): Record<string, unknown> {
  const members = repositories.countMembers(community.communityId);
  return {
    f: channelEo(channel),
    n: channel.name,
    ci: communityInfo(community),
    mc: Math.max(1, members),
    td: channel.description ?? '',
  };
}

export function channelFeed(
  channel: ChannelRow,
  community: CommunityRow,
): Record<string, unknown> {
  const members = repositories.countMembers(community.communityId);
  return {
    f: channelEo(channel),
    n: channel.name,
    a: 'Yes',
    mc: Math.max(1, members),
    fc: communityInfo(community),
    lrt: Date.now(),
    ibt: 'CommunityFeedChannels',
  };
}

export function feedPost(
  item: PostWithAuthor,
  viewerAccountId?: string,
): Record<string, unknown> {
  const { post, author } = item;
  const liked = viewerAccountId
    ? repositories.isLiked(post.postId, viewerAccountId)
    : false;
  const likeCount = repositories.countLikes(post.postId);
  const commentCount = repositories.countComments(post.postId);
  return {
    i: post.postId,
    a: profileAbout(author),
    P: {
      m: {
        u: post.title,
        t: post.title,
        d: post.description ?? '',
        P: 'https://omlet.gg',
        Q: post.title,
        U: post.title,
        oi: { p: author.omletId, t: 'omlet' },
        un: author.omletId,
        id: {
          a: author.accountId,
          t: 'Message',
          id: b64e(Buffer.from(post.postId)),
        },
        usr: {
          a: author.accountId,
          n: author.omletId,
          p: CONFIG.avatarBlobUrl,
          vfs: [],
        },
        gn: [],
        gi: [],
        g: [],
        ct: post.createdMs,
        cc: commentCount,
        l: likeCount,
        yl: liked,
        vd: false,
      },
    },
    ls: { t: String(post.createdMs) },
    ofc: 0,
  };
}

export function commentPayload(
  item: CommentWithAuthor,
): Record<string, unknown> {
  const { comment, author } = item;
  return {
    i: comment.commentId,
    T: 'TEXT',
    b: b64e(Buffer.from(comment.text)),
    t: comment.createdMs,
    u: commentAuthor(author),
    p: commentSubject(author, comment.postId),
  };
}

export function channelMessagePayload(
  item: MessageWithAuthor,
  channel: ChannelRow,
): Record<string, unknown> {
  const { message } = item;
  const body = Buffer.from(
    JSON.stringify({ text: message.text, profileVersion: 0 }),
  );
  return {
    i: { t: 'text', i: message.messageId },
    t: message.createdUs,
    s: message.authorAccountId,
    b: b64e(body),
    f: channelEo(channel),
    d: false,
    rn: message.createdUs,
  };
}

export function postIdFromSubject(subject: unknown): string {
  if (subject && typeof subject === 'object') {
    const raw = (subject as Record<string, unknown>).id;
    if (typeof raw === 'string' && raw.length > 0) {
      let decoded = '';
      try {
        decoded = b64d(raw).toString('utf8');
      } catch {
        decoded = '';
      }
      for (const candidate of [decoded, raw]) {
        if (candidate && repositories.getPost(candidate)) return candidate;
      }
    }
  }
  const latest = repositories.listPosts(1)[0];
  return latest?.post.postId ?? 'local-post-1';
}

export function communityIdFromRequest(request: unknown): string {
  if (request && typeof request === 'object') {
    const value = request as Record<string, any>;
    const cid = value.cid;
    if (cid && typeof cid === 'object') {
      const id = cid.cid ?? cid.a;
      if (typeof id === 'string' && id) return id;
    }
    if (typeof value.ci === 'string' && value.ci) return value.ci;
    if (typeof value.c === 'string' && value.c) return value.c;
  }
  return CONFIG.localCommunityId;
}

export function channelIdFromRequest(request: unknown): string {
  if (request && typeof request === 'object') {
    const value = request as Record<string, any>;
    if (typeof value.a === 'string' && value.a) return value.a;
    if (typeof value.i === 'string' && value.i) return value.i;
  }
  return CONFIG.localChannelId;
}
