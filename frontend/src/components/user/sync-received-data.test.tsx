// @vitest-environment jsdom
import { afterEach, expect, it, vi } from 'vitest';
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { SyncReceivedData } from './sync-received-data';
import { syncReceivedDataService } from '@/lib/api/services/sync-received-data.service';

vi.mock('@/lib/api/services/sync-received-data.service', () => ({
  syncReceivedDataService: { saved: vi.fn() },
}));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

it('loads saved records only when opened and reuses a fresh cached page', async () => {
  vi.mocked(syncReceivedDataService.saved).mockResolvedValue({
    user_id: 'user',
    run_id: 'run',
    provider: 'apple',
    scope: 'user_provider',
    records: [{ value: 42 }],
    next_cursor: null,
  });
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <SyncReceivedData userId="user" runId="run" />
    </QueryClientProvider>
  );
  expect(syncReceivedDataService.saved).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole('button', { name: 'View data' }));
  await screen.findByText(/"value": 42/);
  expect(syncReceivedDataService.saved).toHaveBeenCalledTimes(1);
  expect(
    screen.getByText(/Records are not linked to individual sync runs/)
  ).toBeTruthy();
  fireEvent.click(screen.getByRole('button', { name: 'Close' }));
  await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
  fireEvent.click(screen.getByRole('button', { name: 'View data' }));
  await screen.findByText(/"value": 42/);
  expect(syncReceivedDataService.saved).toHaveBeenCalledTimes(1);
  cleanup();
  client.clear();
});
