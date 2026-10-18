import { describe, expect, it } from 'vitest';

import {
  channelIdFromRequest,
  communityIdFromRequest,
  postIdFromSubject,
  profileAbout,
} from '../src/protocol/builders';
import type { Account } from '../src/db/repositories';
import { b64d, b64e } from '../src/protocol/crypto';

describe('protocol helpers', () => {
  it('round-trips base64', () => {
    const value = Buffer.from('omlet');
    expect(b64d(b64e(value)).toString()).toBe('omlet');
  });

  it('extracts community and channel ids', () => {
    expect(
      communityIdFromRequest({ cid: { cid: 'comunidade-1' } }),
    ).toBe('comunidade-1');
    expect(channelIdFromRequest({ a: 'canal-1' })).toBe('canal-1');
  });

  it('falls back to the local post for an unknown subject', () => {
    expect(postIdFromSubject({ id: b64e(Buffer.from('missing')) })).toBe(
      'local-post-1',
    );
  });

  it('maps account profile fields into the about payload', () => {
    const account: Account = {
      accountId: 'acc-1',
      clientPub: null,
      omletId: 'flutter',
      scopes: [],
      createdMs: 1,
      hasEmail: false,
      hasPassword: false,
      z: {},
      bio: 'minha bio',
      avatarUrl: 'longdan://avatar/x',
      backgroundUrl: 'longdan://bg/y',
      infoImages: ['longdan://img/1'],
      decorationJson: '{"dcb":"longdan://dec/1"}',
    };
    const about = profileAbout(account);
    expect(about.a).toBe('minha bio');
    expect(about.bg).toBe('longdan://bg/y');
    expect(about.p).toEqual(['longdan://img/1']);
    expect(about.fc).toMatchObject({
      m: { ci: 'longdan://avatar/x', dn: 'flutter' },
    });
  });
});
