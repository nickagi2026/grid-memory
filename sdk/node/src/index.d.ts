/** Type declarations for grid-memory Node.js SDK */

export interface WriteOptions {
  tags?: string[];
  ttlSeconds?: number;
  sessionId?: string;
}

export interface FactOptions {
  tags?: string[];
  ttlSeconds?: number;
  agentId?: string;
}

export interface DecideOptions {
  tags?: string[];
  ttlSeconds?: number;
  agentId?: string;
  rationale?: string;
}

export interface HandoffOptions {
  from: string;
  to: string;
  content: string;
  status?: string;
  tags?: string[];
  ttlSeconds?: number;
  agentId?: string;
}

export interface QueryOptions {
  tags?: string[];
  agents?: string[];
  type?: string;
  types?: string[];
  max?: number;
  since?: string;
  tagMode?: 'OR' | 'AND';
  parentEntry?: string;
}

export interface GridEntry {
  id: string;
  agent_id: string;
  type: string;
  tags: string[];
  content: string;
  created_at: string;
  expires_at: string;
  parent_entry: string | null;
}

export interface QueryResult {
  entries: GridEntry[];
  query_meta: {
    total_before_filter: number;
    expired_filtered: number;
    returned: number;
    query: Record<string, unknown>;
  };
}

export interface WriteResult {
  entry_id: string;
  agent_id: string;
  type: string;
  tags: string[];
  created_at: string;
  ttl_seconds: number;
  expires_at: string;
  store_entries_count: number;
}

export interface InfoResult {
  total_entries: number;
  alive_entries: number;
  expired_entries: number;
  unique_agents: number;
  unique_tags: number;
  store_size_kb: number;
  by_type: Record<string, number>;
  by_agent: Record<string, number>;
}

export interface PruneResult {
  removed: number;
  remaining: number;
  total_before: number;
  store_size_mb: number;
  compressed: boolean;
}

export interface ForgetResult {
  found: boolean;
  entry_id?: string;
  type?: string;
  agent_id?: string;
  message?: string;
}

export interface GridOptions {
  defaultAgentId?: string;
  timeout?: number;
}

export class GridError extends Error {
  statusCode?: number;
}

export class Grid {
  constructor(url?: string, options?: GridOptions);
  fact(content: string, options?: FactOptions): Promise<WriteResult>;
  decide(content: string, options?: DecideOptions): Promise<WriteResult>;
  handoff(options: HandoffOptions): Promise<WriteResult>;
  write(agentId: string, type: string, content: string, options?: WriteOptions): Promise<WriteResult>;
  query(options?: QueryOptions): Promise<QueryResult>;
  inject(context?: string): Promise<string>;
  info(): Promise<InfoResult>;
  prune(): Promise<PruneResult>;
  forget(entryId: string): Promise<ForgetResult>;
  health(): Promise<{ status: string; store: Record<string, unknown>; version: string }>;
}
