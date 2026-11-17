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

const STATUS_TEXT: Record<string, string> = {
  partial:
    'Some received data was not captured. Available batches are listed below.',
  not_captured:
    'Received data was not captured for this run. Historical records are not reconstructed.',
  expired: 'Received data has expired. Captures are retained for 72 hours.',
  unavailable: 'Received data storage is unavailable or not configured.',
};

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
          <DialogTitle>Received sync data</DialogTitle>
          <DialogDescription>
            Immutable captures from this sync, retained for 72 hours. Normalized
            captures are labeled and may differ from the original transport
            format.
          </DialogDescription>
        </DialogHeader>
        {open && (
          <ReceivedDataContent
            key={`${userId}:${runId}`}
            userId={userId}
            runId={runId}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ReceivedDataContent({
  userId,
  runId,
}: {
  userId: string;
  runId: string;
}) {
  const [cursor, setCursor] = useState<string | null>(null);
  const [previous, setPrevious] = useState<(string | null)[]>([]);
  const [artifactId, setArtifactId] = useState<string | null>(null);
  const [previewCursor, setPreviewCursor] = useState<string | null>(null);
  const [previewPrevious, setPreviewPrevious] = useState<(string | null)[]>([]);
  const list = useQuery({
    queryKey: ['sync-received-data', userId, runId, cursor],
    queryFn: () => syncReceivedDataService.list(userId, runId, cursor),
    retry: false,
    gcTime: 0,
    staleTime: 0,
  });
  const preview = useQuery({
    queryKey: [
      'sync-received-preview',
      userId,
      runId,
      artifactId,
      previewCursor,
    ],
    queryFn: () =>
      syncReceivedDataService.preview(
        userId,
        runId,
        artifactId!,
        previewCursor
      ),
    enabled: artifactId !== null,
    retry: false,
    gcTime: 0,
    staleTime: 0,
  });

  return (
    <div className="space-y-4 min-w-0">
      <p className="text-xs font-mono break-all text-muted-foreground">
        Run: {runId}
      </p>
      {list.isPending && <p role="status">Loading received data...</p>}
      {list.isError && (
        <div role="alert" className="space-y-2">
          <p>
            Unable to load received data. The run may have expired or be
            unavailable.
          </p>
          <Button variant="outline" size="sm" onClick={() => list.refetch()}>
            Retry
          </Button>
        </div>
      )}
      {list.data && (
        <>
          {STATUS_TEXT[list.data.capture_status] && (
            <p role="status" className="text-sm text-muted-foreground">
              {STATUS_TEXT[list.data.capture_status]}
            </p>
          )}
          {list.data.artifacts.length === 0 &&
            list.data.capture_status === 'available' && (
              <p>No captured batches for this page.</p>
            )}
          <div className="space-y-2">
            {list.data.artifacts.map((artifact) => (
              <button
                key={artifact.artifact_id}
                type="button"
                disabled={artifact.status !== 'available'}
                aria-pressed={artifactId === artifact.artifact_id}
                className="w-full rounded-md border border-border p-3 text-left text-sm disabled:opacity-60 aria-pressed:border-primary"
                onClick={() => {
                  setArtifactId(artifact.artifact_id);
                  setPreviewCursor(null);
                  setPreviewPrevious([]);
                }}
              >
                <span className="block font-medium break-words">
                  {artifact.label}
                </span>
                <span className="block text-xs text-muted-foreground">
                  {artifact.representation === 'original'
                    ? 'Original capture'
                    : 'Normalized snapshot'}{' '}
                  · {artifact.content_type} ·{' '}
                  {artifact.size_bytes.toLocaleString()} bytes ·{' '}
                  {artifact.status}
                </span>
                <span className="block text-xs text-muted-foreground">
                  Captured {new Date(artifact.captured_at).toLocaleString()} ·
                  Expires {new Date(artifact.expires_at).toLocaleString()}
                </span>
              </button>
            ))}
          </div>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              disabled={!previous.length || list.isFetching}
              onClick={() => {
                setCursor(previous[previous.length - 1]);
                setPrevious(previous.slice(0, -1));
                setArtifactId(null);
              }}
            >
              Previous batches
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={!list.data.next_cursor || list.isFetching}
              onClick={() => {
                setPrevious([...previous, cursor]);
                setCursor(list.data!.next_cursor);
                setArtifactId(null);
              }}
            >
              Next batches
            </Button>
          </div>
        </>
      )}
      {artifactId && (
        <section
          className="space-y-2 min-w-0"
          aria-label="Captured data preview"
        >
          <h3 className="font-medium">Data preview</h3>
          {preview.isPending && <p role="status">Loading preview...</p>}
          {preview.isError && (
            <p role="alert">
              Preview unavailable. The capture may have expired.
            </p>
          )}
          {preview.data && (
            <>
              <p className="text-xs text-muted-foreground">
                {preview.data.representation === 'normalized'
                  ? 'Normalized snapshot'
                  : 'Original capture'}
              </p>
              {preview.data.preview.format === 'binary' ? (
                <p>Binary capture retained; text preview is unavailable.</p>
              ) : (
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-all rounded-md bg-muted p-3 text-xs">
                  {preview.data.preview.records !== null
                    ? JSON.stringify(preview.data.preview.records, null, 2)
                    : preview.data.preview.text}
                </pre>
              )}
              {preview.data.preview.truncated && (
                <p className="text-xs text-muted-foreground">
                  Preview is bounded; not all captured content is shown on this
                  page.
                </p>
              )}
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  disabled={!previewPrevious.length || preview.isFetching}
                  onClick={() => {
                    setPreviewCursor(
                      previewPrevious[previewPrevious.length - 1]
                    );
                    setPreviewPrevious(previewPrevious.slice(0, -1));
                  }}
                >
                  Previous records
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  disabled={
                    !preview.data.preview.next_cursor || preview.isFetching
                  }
                  onClick={() => {
                    setPreviewPrevious([...previewPrevious, previewCursor]);
                    setPreviewCursor(preview.data!.preview.next_cursor);
                  }}
                >
                  Next records
                </Button>
              </div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
