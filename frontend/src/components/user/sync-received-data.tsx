import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog';
import { syncReceivedDataService } from '@/lib/api/services/sync-received-data.service';

export function SyncReceivedData({
  userId,
  runId,
}: {
  userId: string;
  runId: string;
}) {
  const [open, setOpen] = useState(false);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          View data
        </Button>
      </DialogTrigger>
      <DialogContent className="w-[calc(100%_-_2rem)] max-w-4xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Saved sync data</DialogTitle>
          <DialogDescription>
            Current processed records saved in the database for this user and
            provider. Records are not linked to individual sync runs. This is
            not a raw capture or a snapshot of this run.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <SavedDataContent
            key={`${userId}:${runId}`}
            userId={userId}
            runId={runId}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function SavedDataContent({
  userId,
  runId,
}: {
  userId: string;
  runId: string;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const data = useQuery({
    queryKey: ['sync-saved-data', userId, runId, cursor],
    queryFn: () => syncReceivedDataService.saved(userId, runId, cursor),
    staleTime: 30_000,
    gcTime: 60_000,
    retry: false,
  });
  return (
    <div className="space-y-4 min-w-0">
      <p className="text-xs font-mono break-all text-muted-foreground">
        Run: {runId}
      </p>
      {data.isPending && <p role="status">Loading saved data...</p>}
      {data.isError && (
        <div role="alert">
          <p>Unable to load saved data.</p>
          <Button variant="outline" size="sm" onClick={() => data.refetch()}>
            Retry
          </Button>
        </div>
      )}
      {data.data && (
        <>
          <p className="text-sm text-muted-foreground">
            Provider: {data.data.provider} · Measurements and events
          </p>
          {data.data.records.length === 0 ? (
            <p>No saved records found for this user and provider.</p>
          ) : (
            <pre className="max-h-96 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
              {JSON.stringify(data.data.records, null, 2)}
            </pre>
          )}
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!previous.length || data.isFetching}
              onClick={() => {
                setCursor(previous[previous.length - 1]);
                setPrevious(previous.slice(0, -1));
              }}
            >
              Previous records
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!data.data.next_cursor || data.isFetching}
              onClick={() => {
                setPrevious([...previous, cursor]);
                setCursor(data.data!.next_cursor);
              }}
            >
              Next records
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
