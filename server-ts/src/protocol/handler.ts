import crypto from 'node:crypto';

import { CONFIG } from '../config';
import {
  type Account,
  type AccountInput,
  repositories,
} from '../db/repositories';
import {
  downloadUrl,
  hasBlob,
  hexFromHashB64,
  hexFromLink,
  linkFromHashB64,
} from '../http/blobs';
import {
  channelFeed,
  channelIdFromRequest,
  channelIo,
  channelMessagePayload,
  commentAuthor,
  commentPayload,
  communityEe,
  communityIdFromRequest,
  feedPost,
  postIdFromSubject,
  profileAbout,
  profileDetail,
  sessionZ,
} from './builders';
import { EnvelopeSchema } from './schemas';
import {
  b64d,
  b64e,
  decodeMessage,
  randomBytes,
  sha256,
  sharedSecret,
} from './crypto';

export interface SocketState {
  clientPub?: string;
  api?: string;
}

type Json = Record<string, any>;

function makeRecord(
  clientPub: string,
  apiKey: string,
  accountId: string,
  omletId: string,
  scopes: string[],
): AccountInput {
  const stamp = Date.now();
  const appId = sha256([
    Buffer.from(`${clientPub}${apiKey}appid`, 'utf8'),
  ]).toString('base64');
  return {
    accountId,
    clientPub: clientPub || null,
    omletId,
    scopes,
    createdMs: stamp,
    hasEmail: true,
    hasPassword: true,
    z: {
      a: {
        a: accountId,
        c: 'ONE',
        d: 'GUEST',
        i: [{ p: omletId, t: 'omlet' }],
        p: omletId,
        s: stamp,
      },
      S: scopes,
      i: appId,
      e: true,
      p: false,
    },
  };
}

function getOrCreateRecord(
  clientPub: string,
  apiKey: string,
  accountId?: string,
): Account {
  const found = repositories.findAccount(accountId, clientPub || undefined);
  if (found) return found;
  const id = accountId || clientPub || crypto.randomUUID().replaceAll('-', '');
  return repositories.upsertAccount(
    makeRecord(
      clientPub,
      apiKey,
      id,
      repositories.uniqueGuestOmletId(),
      ['PublicProfile', 'Arcade'],
    ),
  );
}

function currentAccount(state: SocketState): Account {
  return getOrCreateRecord(state.clientPub ?? '', state.api ?? '', undefined);
}

function base64Text(value: unknown): string {
  if (typeof value !== 'string' || !value) return '';
  try {
    return b64d(value).toString('utf8');
  } catch {
    return '';
  }
}

function decodeChannelText(value: unknown): string {
  const raw = base64Text(value);
  try {
    const parsed = JSON.parse(raw) as { text?: unknown };
    if (parsed && typeof parsed.text === 'string') return parsed.text;
  } catch {
    // Legacy/plain text payload.
  }
  return raw;
}

function ensureLocalChannel(account: Account) {
  let community = repositories.getCommunity(CONFIG.localCommunityId);
  if (!community) {
    community = repositories.insertCommunity(
      CONFIG.localCommunityId,
      'Comunidade Local',
      'Comunidade local de testes',
      CONFIG.avatarBlobUrl,
      CONFIG.coverBlobUrl,
      account.accountId,
    );
    repositories.addMember(
      community.communityId,
      account.accountId,
      'owner',
    );
  }
  let channel = repositories.getChannel(CONFIG.localChannelId);
  if (!channel) {
    channel = repositories.insertChannel(
      CONFIG.localChannelId,
      community.communityId,
      'geral',
      'Canal de texto da comunidade',
      CONFIG.localChannelKey,
    );
  }
  return { community, channel };
}

function authorMap(
  items: Array<{ author: Account }>,
): Record<string, unknown> {
  const map: Record<string, unknown> = {};
  for (const item of items) {
    map[item.author.accountId] = commentAuthor(item.author);
  }
  return map;
}

export class LongdanHandler {
  private log(message: string, data?: unknown): void {
    const suffix = data === undefined ? '' : ` ${JSON.stringify(data)}`;
    console.log(`${new Date().toISOString()} ${message}${suffix}`);
  }

  async handle(
    raw: Buffer | ArrayBuffer | string,
    state: SocketState,
    path: string,
  ): Promise<string | null> {
    let request: Json;
    try {
      const parsed = EnvelopeSchema.safeParse(decodeMessage(raw));
      if (!parsed.success) {
        this.log('BAD_MESSAGE', { path, error: parsed.error.message });
        return null;
      }
      request = parsed.data as Json;
    } catch (error) {
      this.log('BAD_MESSAGE', { path, error: String(error) });
      return null;
    }

    this.log('REQ', { path, request });
    const q = (request.q ?? {}) as Json;
    const response: Json = { '#': q['#'] };

    try {
      if ('*' in q) {
        const hello = (q['*'] ?? {}) as Json;
        state.clientPub = String(hello.k ?? '');
        state.api = String(hello.a ?? '');
        try {
          const shared = sharedSecret(state.clientPub);
          const serverNonce = randomBytes(32);
          const digest = sha256([
            Buffer.from([0x01]),
            shared,
            b64d(String(hello.c ?? '')),
          ]);
          response['*'] = {
            c: b64e(serverNonce),
            r: b64e(digest),
          };
          this.log('HANDSHAKE', { path, api: state.api });
        } catch (error) {
          this.log('HANDSHAKE_FAILED', { path, error: String(error) });
          response['!'] = 'HandshakeFailed';
          response['!!'] = String(error);
        }
      } else if ('-' in q) {
        response['-'] = { t: Date.now() };
      } else if ('+' in q) {
        this.log('HELLO', { path, payload: q['+'] });
        response['+'] = { l: 'ONE' };
      } else if (q.a && typeof q.a === 'object' && 'l' in q.a) {
        const resume = (q.a.l ?? {}) as Json;
        const accountId =
          typeof resume.p === 'string' ? resume.p : undefined;
        const record = repositories.findAccount(
          accountId,
          state.clientPub || undefined,
        );
        if (record) {
          response.a = { a: sessionZ(record) };
          this.log('QB_RESUME', {
            path,
            account: record.accountId,
            omlet_id: record.omletId,
          });
        } else {
          response['!'] = 'NotSignedIn';
          this.log('QB_NO_ACCOUNT', { path, client_pub: state.clientPub });
        }
      } else if (q.a && typeof q.a === 'object' && 'cis' in q.a) {
        response.a = { cis: { s: 'Success' } };
        this.log('CHECK_IDENTITY', { path, payload: q.a.cis });
      } else if (q.a && typeof q.a === 'object' && 'ci' in q.a) {
        const ci = (q.a.ci ?? {}) as Json;
        const identity = (ci.i ?? {}) as Json;
        const idType = typeof identity.t === 'string' ? identity.t : '';
        const idValue = typeof identity.p === 'string' ? identity.p : '';
        if (idType === 'omlet' && idValue) {
          const available = repositories.isOmletIdAvailable(
            idValue,
            state.clientPub || undefined,
          );
          response['='] = { v: available };
          this.log('CHECK_ID', {
            path,
            omlet_id: idValue,
            available,
          });
        } else {
          response['='] = { v: true };
          this.log('CHECK_ID', { path, type: idType });
        }
      } else if (q.a && typeof q.a === 'object' && 'sc' in q.a) {
        const sc = (q.a.sc ?? {}) as Json;
        const omletId = String(sc.s ?? 'omletplayer').trim() || 'omletplayer';
        const accountId = String(
          sc.a ?? crypto.randomUUID().replaceAll('-', ''),
        );
        const scopes = Array.isArray(sc.S)
          ? sc.S.map(String)
          : ['PublicProfile', 'Arcade'];
        if (
          !repositories.isOmletIdAvailable(omletId, state.clientPub || undefined)
        ) {
          response['!'] = 'IdentityAlreadyExists';
          this.log('CREATE_ACCOUNT_DUPLICATE', {
            path,
            account: accountId,
            omlet_id: omletId,
          });
        } else {
          const record = repositories.upsertAccount(
            makeRecord(
              state.clientPub ?? '',
              state.api ?? '',
              accountId,
              omletId,
              scopes,
            ),
          );
          response.a = { sc: { s: 'GUEST', a: record.z } };
          this.log('CREATE_ACCOUNT', {
            path,
            account: accountId,
            omlet_id: omletId,
            scopes,
          });
        }
      } else if (q.p && typeof q.p === 'object' && 'spat' in q.p) {
        const req = (q.p.spat ?? {}) as Json;
        const record = currentAccount(state);
        const bio = typeof req.u === 'string' ? req.u.slice(0, 1500) : '';
        repositories.updateBio(record.accountId, bio);
        response['='] = { v: true };
        this.log('SET_PROFILE_ABOUT', { path, bio });
      } else if (q.p && typeof q.p === 'object' && 'spbg' in q.p) {
        const req = (q.p.spbg ?? {}) as Json;
        const record = currentAccount(state);
        const link = typeof req.p === 'string' ? req.p : '';
        repositories.updateBackgroundUrl(record.accountId, link);
        response['='] = { v: true };
        this.log('SET_PROFILE_BACKGROUND', { path, link });
      } else if (q.p && typeof q.p === 'object' && 'spbl' in q.p) {
        const req = (q.p.spbl ?? {}) as Json;
        const record = currentAccount(state);
        const links = Array.isArray(req.p)
          ? req.p.filter((item): item is string => typeof item === 'string')
          : [];
        repositories.updateInfoImages(record.accountId, links);
        response['='] = { v: true };
        this.log('SET_PROFILE_INFO_IMAGES', { path, count: links.length });
      } else if (q.p && typeof q.p === 'object' && 'spd' in q.p) {
        const req = (q.p.spd ?? {}) as Json;
        const record = currentAccount(state);
        if (req.pd && typeof req.pd === 'object') {
          repositories.updateDecoration(
            record.accountId,
            JSON.stringify(req.pd),
          );
          this.log('SET_PROFILE_DECORATION', {
            path,
            fields: Object.keys(req.pd),
          });
        } else {
          repositories.updateDecoration(record.accountId, '');
          this.log('RESET_PROFILE_DECORATION', { path });
        }
        response['='] = { v: true };
      } else if (q.p && typeof q.p === 'object' && 'gu' in q.p) {
        response.p = { gu: { a: {}, b: {} } };
        this.log('GET_UNLOCKS', { path });
      } else if (q.p && typeof q.p === 'object' && 'cpf' in q.p) {
        const cpf = (q.p.cpf ?? {}) as { pf?: string[] };
        const features = Array.isArray(cpf.pf) ? cpf.pf : [];
        const pf: Record<string, boolean> = {};
        for (const feature of features) pf[feature] = true;
        response.p = { cpf: { pf, r: true } };
        this.log('CHECK_PREMIUM', { path, count: features.length });
      } else if (q.p && typeof q.p === 'object' && 'gx' in q.p) {
        response.p = { gx: {} };
        this.log('USER_COUNTS', { path });
      } else if (q.p && typeof q.p === 'object' && 'gmg' in q.p) {
        response.p = { gmg: { mp: [] } };
        this.log('MISSION_GROUPS', { path });
      } else if (q.p && typeof q.p === 'object' && 'gpa' in q.p) {
        const gpa = (q.p.gpa ?? {}) as Json;
        const accountId =
          typeof gpa.c === 'string'
            ? gpa.c
            : typeof gpa.a === 'string'
              ? gpa.a
              : undefined;
        const record = getOrCreateRecord(
          state.clientPub ?? '',
          state.api ?? '',
          accountId,
        );
        response.p = {
          pa: { p: profileAbout(record), us: {} },
        };
        this.log('PROFILE', {
          path,
          account: record.accountId,
          omlet_id: record.omletId,
        });
      } else if (q.p && typeof q.p === 'object' && 'c' in q.p) {
        const pc = (q.p.c ?? {}) as Json;
        const accountId =
          typeof pc.c === 'string' ? pc.c : undefined;
        const record = getOrCreateRecord(
          state.clientPub ?? '',
          state.api ?? '',
          accountId,
        );
        response.p = { c: { p: profileDetail(record) } };
        this.log('PROFILE_DETAIL', {
          path,
          account: record.accountId,
          omlet_id: record.omletId,
        });
      } else if (q.p && typeof q.p === 'object' && 'gbl' in q.p) {
        response.p = { gbl: { bu: [], ui: [] } };
        this.log('BLOCKED_USERS', { path, payload: q.p.gbl });
      } else if (q.p && typeof q.p === 'object' && 'guti' in q.p) {
        response.p = { guti: { l: [], us: {} } };
        this.log('USER_TROPHIES', { path, payload: q.p.guti });
      } else if (q.p && typeof q.p === 'object' && 'gru' in q.p) {
        response.p = { gru: { i: '', t: '', u: '' } };
        this.log('URL_RESOLVE', { path, payload: q.p.gru });
      } else if (q.p && typeof q.p === 'object' && 'gad' in q.p) {
        response.p = { gad: { f: {}, d: {}, pf: [], ph: [], v: 0 } };
        this.log('AVAILABLE_DECORATIONS', { path, payload: q.p.gad });
      } else if (q.p && typeof q.p === 'object' && 'gdr' in q.p) {
        response.p = { gdr: { l: [], t: '', v: 0 } };
        this.log('PURCHASED_DECORATIONS', { path, payload: q.p.gdr });
      } else if (q.w && typeof q.w === 'object' && anyKey(q.w, ['gfc', 'gafc', 'guwc'])) {
        const record = currentAccount(state);
        const keys = Object.keys(q.w);
        response['='] = {
          v: keys.includes('guwc')
            ? repositories.countPostsByAuthor(record.accountId)
            : 0,
        };
        this.log('COUNT', { path, keys, value: response['='].v });
      } else if (q.w && typeof q.w === 'object' && 'gcvv' in q.w) {
        const req = (q.w.gcvv ?? {}) as Json;
        const postId = postIdFromSubject(req.id);
        const comments = repositories.listComments(postId);
        response.w = {
          gcvv: { C: comments.map(commentPayload) },
        };
        this.log('COMMENTS_LIST', {
          path,
          post: postId,
          count: comments.length,
        });
      } else if (q.w && typeof q.w === 'object' && 'ac' in q.w) {
        const req = (q.w.ac ?? {}) as Json;
        const text = base64Text(req.b);
        const postId = postIdFromSubject(req.id);
        const record = currentAccount(state);
        repositories.addComment(
          postId,
          record.accountId,
          text,
          typeof req.i === 'string' ? req.i : null,
        );
        response['='] = { v: true };
        this.log('COMMENT_ADD', {
          path,
          post: postId,
          text,
          count: repositories.countComments(postId),
        });
      } else if (q.w && typeof q.w === 'object' && 'l' in q.w) {
        const req = (q.w.l ?? {}) as Json;
        const liked = Boolean(req.l);
        const postId = postIdFromSubject(req.ud);
        const record = currentAccount(state);
        const count = repositories.setLike(
          postId,
          record.accountId,
          liked,
        );
        response['='] = { v: true };
        this.log('LIKE', { path, post: postId, liked, count });
      } else if (q.w && typeof q.w === 'object' && 'ghp' in q.w) {
        const record = currentAccount(state);
        const items = repositories.listPosts();
        const posts =
          items.length > 0
            ? items
            : [repositories.ensureSeedPost(record)];
        response.w = {
          ghp: {
            p: posts.map((item) => feedPost(item, record.accountId)),
          },
        };
        this.log('FEED', { path, posts: posts.length });
      } else if (q.w && typeof q.w === 'object' && 'guw' in q.w) {
        const req = (q.w.guw ?? {}) as Json;
        const viewer = currentAccount(state);
        const authorId =
          typeof req.a === 'string' ? req.a : viewer.accountId;
        const author = repositories.findAccount(authorId) ?? viewer;
        const posts = repositories
          .listPosts(100)
          .filter((item) => item.post.authorAccountId === author.accountId);
        response.w = {
          w: {
            w: {
              p: posts.map((item) => feedPost(item, viewer.accountId).P),
            },
          },
        };
        this.log('USER_WALL', { path, author: authorId, count: posts.length });
      } else if (q.w && typeof q.w === 'object' && 'gg' in q.w) {
        const req = (q.w.gg ?? {}) as Json;
        const viewer = currentAccount(state);
        const accountId =
          typeof req.u === 'string' ? req.u : viewer.accountId;
        let communities = repositories.listCommunities(accountId);
        if (communities.length === 0) communities = repositories.listCommunities();
        const items = communities.map((community) => ({
          p: {
            ct: 'Managed',
            cid: community.communityId,
            p: 'Android',
          },
          cic: communityEe(community, accountId),
        }));
        response.w = { gcm: { c: items, p: items.length } };
        this.log('PROFILE_GAMES', { path, account: accountId, count: items.length });
      } else if (q.w && typeof q.w === 'object' && 'ltr' in q.w) {
        response.w = {
          ltr: { mt: [], cic: [], gf: [], gfs: {}, tt: {} },
        };
        this.log('PROFILE_TOURNAMENTS', { path });
      } else if (q.w && typeof q.w === 'object' && 'ci' in q.w) {
        response.w = { ci: { i: false, r: false } };
        this.log('PROFILE_COMMUNITY_INFO', { path, payload: q.w.ci });
      } else if (q.w && typeof q.w === 'object' && 'gubpc' in q.w) {
        response['='] = { v: 0 };
        this.log('BANG_POST_COUNT', { path, payload: q.w.gubpc });
      } else if (q.w && typeof q.w === 'object' && 'gubw' in q.w) {
        response.w = { w: { w: { p: [], i: [] } } };
        this.log('BANG_WALL', { path, payload: q.w.gubw });
      } else if (q.w && typeof q.w === 'object' && 'gthr' in q.w) {
        response.w = { gthr: { hl: [] } };
        this.log('HIGHLIGHTS', { path, payload: q.w.gthr });
      } else if (q.w && typeof q.w === 'object' && 'gspt' in q.w) {
        response.w = { gspt: {} };
        this.log('SERVER_PING_STATS', { path, payload: q.w.gspt });
      } else if (q.w && typeof q.w === 'object' && 'gaf' in q.w) {
        response.w = { gaf: { f: [] } };
        this.log('ACCOUNTS_FOLLOWED', { path, payload: q.w.gaf });
      } else if (q.st && typeof q.st === 'object' && 'gtf' in q.st) {
        response.st = { gtf: { al: [], u: [] } };
        this.log('PROFILE_TOP_FANS', { path });
      } else if (q.st && typeof q.st === 'object' && 'grl' in q.st) {
        response.st = { grl: { l: [] } };
        this.log('PROFILE_REWARD_LEVEL', { path });
      } else if (q.r && typeof q.r === 'object' && 'm' in q.r) {
        response['!'] = 'NotASquadMember';
        this.log('ABOUT_SQUAD', { path, payload: q.r.m });
      } else if (q.w && typeof q.w === 'object' && 'gcfr' in q.w) {
        const record = currentAccount(state);
        let communities = repositories.listCommunities(record.accountId);
        if (communities.length === 0) communities = repositories.listCommunities();
        let items = repositories.listPosts();
        if (items.length === 0) items = [repositories.ensureSeedPost(record)];
        const header = {
          i: 'my-communities',
          c: communities.map((community) =>
            communityEe(community, record.accountId),
          ),
        };
        response.w = {
          ghp: {
            p: [
              header,
              ...items.map((item) => feedPost(item, record.accountId)),
            ],
          },
        };
        this.log('COMMUNITY_FEED', {
          path,
          communities: communities.length,
          posts: items.length,
        });
      } else if (q.w && typeof q.w === 'object' && anyKey(q.w, ['grp', 'gtp', 'grgw'])) {
        const record = currentAccount(state);
        let items = repositories.listPosts();
        if (items.length === 0) items = [repositories.ensureSeedPost(record)];
        response.w = {
          w: {
            w: {
              p: items.map((item) => feedPost(item, record.accountId).P),
            },
          },
        };
        this.log('COMMUNITY_POSTS', {
          path,
          keys: Object.keys(q.w),
          count: items.length,
        });
      } else if (q.w && typeof q.w === 'object' && 'lrcmc' in q.w) {
        const record = currentAccount(state);
        const communities = repositories.listCommunities();
        response.w = {
          lrcmc: {
            cic: communities.map((community) =>
              communityEe(community, record.accountId),
            ),
          },
        };
        this.log('BROWSE_COMMUNITIES', {
          path,
          count: communities.length,
        });
      } else if (q.w && typeof q.w === 'object' && 'licu' in q.w) {
        const record = currentAccount(state);
        const communities = repositories.listCommunities(record.accountId);
        const items = communities.map((community) => ({
          p: {
            ct: 'Managed',
            cid: community.communityId,
            p: 'Android',
          },
          cic: communityEe(community, record.accountId),
        }));
        response.w = {
          gcm: { c: items, p: items.length },
        };
        this.log('COMMUNITIES', { path, count: items.length });
      } else if (q.w && typeof q.w === 'object' && 'cmc' in q.w) {
        const req = (q.w.cmc ?? {}) as Json;
        const record = currentAccount(state);
        const name =
          typeof req.n === 'string' && req.n.trim()
            ? req.n.trim().slice(0, 50)
            : 'Comunidade Local';
        const description =
          typeof req.d === 'string' && req.d.trim()
            ? req.d.trim().slice(0, 1500)
            : 'Comunidade local de testes';
        const icon =
          typeof req.i === 'string' && req.i
            ? req.i
            : CONFIG.avatarBlobUrl;
        const cover =
          typeof req.b === 'string' && req.b
            ? req.b
            : CONFIG.coverBlobUrl;
        const community = repositories.createCommunity(
          name,
          description,
          icon,
          cover,
          record.accountId,
        );
        repositories.createChannel(
          community.communityId,
          'geral',
          'Canal de texto da comunidade',
        );
        response.w = {
          cmc: {
            cic: communityEe(community, record.accountId),
          },
        };
        this.log('CREATE_COMMUNITY', {
          path,
          id: community.communityId,
          name,
        });
      } else if (q.w && typeof q.w === 'object' && 'lmcf' in q.w) {
        const req = (q.w.lmcf ?? {}) as Json;
        const communityId = communityIdFromRequest(req);
        const community = repositories.getCommunity(communityId);
        const channels = repositories.listChannels(communityId);
        response.w = {
          lmcf: {
            df: [],
            f:
              community === null
                ? []
                : channels.map((channel) => channelIo(channel, community)),
          },
        };
        this.log('COMMUNITY_CHANNELS', {
          path,
          community: communityId,
          count: channels.length,
        });
      } else if (q.w && typeof q.w === 'object' && 'lmmc' in q.w) {
        const req = (q.w.lmmc ?? {}) as Json;
        const communityId = communityIdFromRequest(req);
        const record = currentAccount(state);
        let members = repositories.listMembers(communityId);
        if (members.length === 0) {
          repositories.addMember(communityId, record.accountId, 'owner');
          members = repositories.listMembers(communityId);
        }
        response.w = {
          lmmc: {
            f: members.map((member) => ({
              a: member.account.accountId,
              n: member.account.omletId,
              p: CONFIG.avatarBlobUrl,
              vfs: [],
              fs: member.role === 'owner' || member.role === 'admin',
            })),
          },
        };
        this.log('COMMUNITY_MEMBERS', {
          path,
          community: communityId,
          count: members.length,
        });
      } else if (q.w && typeof q.w === 'object' && 'ut' in q.w) {
        response.w = {
          ut: { ut: { a: true, l: CONFIG.avatarBlobUrl } },
        };
        this.log('BLOB_UPLOAD', { path, category: 'w' });
      } else if (q.i && typeof q.i === 'object' && 'f' in q.i) {
        const req = (q.i.f ?? {}) as Json;
        const itemType = typeof req.ibt === 'string' ? req.ibt : null;
        if (itemType === 'CommunityFeedChannels') {
          const record = currentAccount(state);
          let channels = repositories.listChannels(undefined, record.accountId);
          if (channels.length === 0) channels = repositories.listChannels();
          const feeds = channels
            .map((channel) => {
              const community = repositories.getCommunity(
                channel.communityId,
              );
              return community ? channelFeed(channel, community) : null;
            })
            .filter((value): value is Record<string, unknown> => value !== null);
          response.i = { f: { f: feeds } };
          this.log('CHANNELS', { path, count: feeds.length });
        } else {
          response.i = { f: { f: [] } };
          this.log('FEED_DETAILS', { path, ibt: itemType, count: 0 });
        }
      } else if (q.i && typeof q.i === 'object' && 'gius' in q.i) {
        response.i = { gius: { m: 0, c: 0, r: 0, ct: 0 } };
        this.log('INBOX_UNREAD', { path });
      } else if (q.i && typeof q.i === 'object' && 'sius' in q.i) {
        response['='] = { v: true };
        this.log('SET_INBOX_READ', { path, payload: q.i.sius });
      } else if (q.co && typeof q.co === 'object' && 'lcos' in q.co) {
        response.co = { lcos: { l: [] } };
        this.log('COMMUNITY_OBJECTS', { path, payload: q.co.lcos });
      } else if (q.m && typeof q.m === 'object' && 'gmfc' in q.m) {
        const record = currentAccount(state);
        const req = (q.m.gmfc ?? {}) as Json;
        let channel = repositories.getChannel(
          channelIdFromRequest(req.f),
        );
        if (!channel) {
          const local = ensureLocalChannel(record);
          channel = local.channel;
        }
        let community = repositories.getCommunity(channel.communityId);
        if (!community) {
          const local = ensureLocalChannel(record);
          community = local.community;
        }
        let messages = repositories.listMessages(channel.channelId);
        if (messages.length === 0) {
          repositories.addMessage(
            channel.channelId,
            record.accountId,
            'Bem-vindo ao canal geral da Comunidade Local!',
          );
          messages = repositories.listMessages(channel.channelId);
        }
        response.m = {
          wd: {
            c: messages.map((message) =>
              channelMessagePayload(message, channel!),
            ),
            p: false,
            s: authorMap(messages),
            fd: channelFeed(channel, community),
          },
        };
        this.log('CHANNEL_MESSAGES', {
          path,
          channel: channel.channelId,
          count: messages.length,
        });
      } else if (q.m && typeof q.m === 'object' && 'o' in q.m) {
        const op = (q.m.o ?? {}) as Json;
        const messageId = (op.i ?? {}) as Json;
        const messageType =
          typeof messageId.t === 'string' ? messageId.t : null;
        const channelId = channelIdFromRequest(op.f);
        if (messageType === 'text' && op.b) {
          const record = currentAccount(state);
          const text = decodeChannelText(op.b);
          repositories.addMessage(
            channelId,
            record.accountId,
            text,
            typeof messageId.i === 'string' ? messageId.i : null,
            undefined,
            typeof messageId.i === 'string' ? messageId.i : null,
          );
          this.log('CHANNEL_SEND', {
            path,
            channel: channelId,
            type: messageType,
            text,
            count: repositories.countMessages(channelId),
          });
        } else {
          this.log('CHANNEL_ACTIVITY', {
            path,
            type: messageType,
          });
        }
        response['='] = { v: true };
      } else if (q.p && typeof q.p === 'object' && 'sab' in q.p) {
        response['='] = { v: true };
        this.log('SET_BIRTHDAY', { path });
      } else if (q.p && typeof q.p === 'object' && 'spgr' in q.p) {
        response['='] = { v: true };
        this.log('SET_GENDER', { path });
      } else if (q.p && typeof q.p === 'object' && 'gui' in q.p) {
        response.p = { gui: { ii: {} } };
        this.log('SHARDS', { path });
      } else if (q.p && typeof q.p === 'object') {
        const keys = Object.keys(q.p);
        if (keys.some((key) => key.startsWith('s'))) {
          response['='] = { v: true };
          this.log('SET_PROFILE', { path, keys });
        } else {
          this.log('UNKNOWN', { path, payload: q });
          response['!'] = 'NotImplemented';
        }
      } else if (q.ps && typeof q.ps === 'object' && 'o' in q.ps) {
        response['='] = { v: true };
        this.log('SET_PRESENCE', { path });
      } else if (q.ps && typeof q.ps === 'object' && 'g' in q.ps) {
        const req = q.ps.g as { A?: string[] };
        const accounts = Array.isArray(req?.A) ? req.A : [];
        response.ps = {
          p: { S: accounts.map((account) => ({ a: account, o: false })) },
        };
        this.log('GET_PRESENCE', { path, count: accounts.length });
      } else if (q.ps && typeof q.ps === 'object' && 'grrc' in q.ps) {
        response.ps = { grrc: { u: [] } };
        this.log('RECENT_ROOMS', { path });
      } else if (q.M && typeof q.M === 'object' && 'R' in q.M) {
        response['='] = { v: true };
        this.log('CONTROL_EVENTS', { path });
      } else if (q.w && typeof q.w === 'object' && 'hif' in q.w) {
        response['='] = { v: true };
        this.log('VIEW_EVENTS', { path });
      } else if (q.w && typeof q.w === 'object' && 'apv' in q.w) {
        response['='] = { v: true };
        this.log('PROFILE_VIEW', { path });
      } else if (q.w && typeof q.w === 'object' && 'saus' in q.w) {
        response.w = { saus: {} };
        this.log('USER_STATS', { path });
      } else if (q.w && typeof q.w === 'object' && 'gci' in q.w) {
        response['='] = { v: true };
        this.log('CLIENT_APPS', { path });
      } else if (q.w && typeof q.w === 'object' && 'gfcl' in q.w) {
        response.w = { gfcl: { ci: [] } };
        this.log('CONTENT_LIST', { path });
      } else if (q.i && typeof q.i === 'object' && 'S' in q.i) {
        response['='] = { v: true };
        this.log('SESSION_PING', { path });
      } else if (q.i && typeof q.i === 'object' && 'ltfs' in q.i) {
        response.i = { ltfs: { lt: [] } };
        this.log('TOURNAMENT_FEED', { path });
      } else if (q.i && typeof q.i === 'object' && 'a' in q.i) {
        response['='] = { v: true };
        this.log('PUSH_REGISTER', { path });
      } else if (q.ff && typeof q.ff === 'object' && 'lg' in q.ff) {
        response.ff = { lg: { g: [] } };
        this.log('ABOUT_COMMUNITIES', { path });
      } else if (q.ca && typeof q.ca === 'object' && 'gnw' in q.ca) {
        response.ca = {
          gnw: { wa: '', bnc: '', hpg: false },
        };
        this.log('WALLET_ADDRESS', { path });
      } else if (q.ca && typeof q.ca === 'object' && 'lett' in q.ca) {
        response.ca = {
          lett: { ts: [] },
        };
        this.log('WALLET_TX', { path });
      } else if (q.ca && typeof q.ca === 'object' && 'g' in q.ca) {
        response.ca = {
          g: { d: [], l: [], m: [], u: [], w: [] },
        };
        this.log('TOP_SUPPORTERS', { path });
      } else if (q.ca && typeof q.ca === 'object' && 'gbp' in q.ca) {
        response.ca = { gbp: { ps: [] } };
        this.log('CRYPTO_PROVIDERS', { path });
      } else if (q.ca && typeof q.ca === 'object' && 'gsbt' in q.ca) {
        response.ca = { gsbt: { ts: [], cs: [] } };
        this.log('CRYPTO_TOKENS', { path });
      } else if (q.b && typeof q.b === 'object' && 'ut' in q.b) {
        const ut = (q.b.ut ?? {}) as Json;
        const meta = (ut.m ?? {}) as Json;
        const hashB64 = typeof meta.h === 'string' ? meta.h : '';
        const size = typeof meta.s === 'number' ? meta.s : 0;
        const hex = hashB64 ? hexFromHashB64(hashB64) : null;
        const link = hashB64 ? linkFromHashB64(hashB64) : CONFIG.avatarBlobUrl;
        const exists = hex !== null && hasBlob(hex);
        if (exists || hex === null) {
          response.b = { ut: { ut: { a: true, l: link } } };
        } else {
          response.b = {
            ut: { ut: { a: false, l: link, u: downloadUrl(hex), h: {} } },
          };
        }
        this.log('BLOB_UPLOAD', { path, hash: hex, size, exists });
      } else if (q.b && typeof q.b === 'object' && 'vc' in q.b) {
        const vc = (q.b.vc ?? {}) as Json;
        const inner = (vc.ut ?? {}) as Json;
        const link = typeof inner.l === 'string' ? inner.l : '';
        response['='] = { v: link };
        this.log('BLOB_UPLOAD_FINALIZE', { path, link });
      } else if (q.b && typeof q.b === 'object' && 'dt' in q.b) {
        const dt = (q.b.dt ?? {}) as Json;
        const source = typeof dt.l === 'string' ? dt.l : '';
        const hex = hexFromLink(source);
        const stored = hex !== null && hasBlob(hex);
        const url = stored
          ? downloadUrl(hex as string)
          : source.includes('/cover/')
            ? CONFIG.coverHttpUrl
            : CONFIG.avatarHttpUrl;
        response.b = {
          dt: { dt: { u: url, h: {} }, pp: CONFIG.blobBase },
        };
        this.log('BLOB_TICKET', { path, source, stored });
      } else {
        this.log('UNKNOWN', { path, payload: q });
        response['!'] = 'NotImplemented';
      }
    } catch (error) {
      this.log('HANDLER_ERROR', { path, error: String(error) });
      throw error;
    }

    return JSON.stringify({ r: response });
  }
}

function anyKey(object: Json, keys: string[]): boolean {
  return keys.some((key) => key in object);
}

export const longdanHandler = new LongdanHandler();
