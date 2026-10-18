import { describe, expect, it } from 'vitest';

import {
  channelIdFromRequest,
  communityIdFromRequest,
  postIdFromSubject,
} from '../src/protocol/builders';
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
});
