import { beforeEach, describe, expect, it, vi } from 'vitest';
import { apiClient } from '../client';
import { syncReceivedDataService } from './sync-received-data.service';

vi.mock('../client', () => ({ apiClient: { get: vi.fn() } }));

beforeEach(() => vi.clearAllMocks());

describe('sync received data service', () => {
  it('scopes the list to the encoded user and run with bounded pagination', () => {
    syncReceivedDataService.list('user', 'run/one', 'opaque-cursor');
    expect(apiClient.get).toHaveBeenCalledWith(
      '/api/v1/users/user/sync/runs/run%2Fone/received-data',
      { params: { limit: 20, cursor: 'opaque-cursor' } }
    );
  });

  it('scopes previews to the artifact and passes preview cursor', () => {
    syncReceivedDataService.preview('user', 'run', 'artifact/one', 'next');
    expect(apiClient.get).toHaveBeenCalledWith(
      '/api/v1/users/user/sync/runs/run/received-data/artifact%2Fone',
      { params: { limit: 100, cursor: 'next' } }
    );
  });

  it('omits unset cursors', () => {
    syncReceivedDataService.list('user', 'run');
    expect(apiClient.get).toHaveBeenCalledWith(
      '/api/v1/users/user/sync/runs/run/received-data',
      { params: { limit: 20 } }
    );
  });
});
