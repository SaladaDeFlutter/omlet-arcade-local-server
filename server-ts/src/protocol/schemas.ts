import { z } from 'zod';

export const EnvelopeSchema = z
  .object({
    q: z.record(z.string(), z.unknown()).default({}),
  })
  .passthrough();

export type Envelope = z.infer<typeof EnvelopeSchema>;
