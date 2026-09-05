export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  is_active: boolean;
  telegram_chat_id: string | null;
}

export interface HealthStatus {
  status: 'ok' | 'degraded' | 'down';
  version: string;
  checks: Record<string, string>;
}
