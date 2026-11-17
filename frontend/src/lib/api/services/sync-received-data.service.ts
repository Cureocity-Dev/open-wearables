import { apiClient } from '../client';

export interface SyncArtifact {
  artifact_id: string;
  captured_at: string;
  expires_at: string;
  representation: 'original' | 'normalized';
  kind: string;
  content_type: string;
  size_bytes: number;
  status: 'available' | 'oversized' | 'failed' | 'expired';
  label: string;
}

export interface ReceivedData {
  run_id: string;
  user_id: string;
  expires_at: string | null;
  capture_status:
    | 'available'
    | 'partial'
    | 'not_captured'
    | 'expired'
    | 'unavailable';
  artifacts: SyncArtifact[];
  next_cursor: string | null;
}

export interface ReceivedDataPreview {
  artifact_id: string;
  representation: 'original' | 'normalized';
  content_type: string;
  size_bytes: number;
  preview: {
    format: 'json_records' | 'text' | 'binary';
    records: unknown[] | null;
    text: string | null;
    truncated: boolean;
    next_cursor: string | null;
  };
}

function path(userId: string, runId: string): string {
  return `/api/v1/users/${encodeURIComponent(userId)}/sync/runs/${encodeURIComponent(runId)}/received-data`;
}

export const syncReceivedDataService = {
  list(userId: string, runId: string, cursor?: string | null) {
    return apiClient.get<ReceivedData>(path(userId, runId), {
      params: { limit: 20, ...(cursor ? { cursor } : {}) },
    });
  },
  preview(
    userId: string,
    runId: string,
    artifactId: string,
    cursor?: string | null
  ) {
    return apiClient.get<ReceivedDataPreview>(
      `${path(userId, runId)}/${encodeURIComponent(artifactId)}`,
      { params: { limit: 100, ...(cursor ? { cursor } : {}) } }
    );
  },
};
