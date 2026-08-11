/**
 * AnimaLink triage client (TypeScript / React Native / Web)
 *
 * Usage:
 *   const client = new AnimaTriageClient({
 *     baseUrl: "http://127.0.0.1:8000",
 *     apiKey: undefined, // or process.env.ANIMA_API_KEY
 *   });
 *   const result = await client.query({
 *     question: "小狗吃了巧克力，精神还行，有点担心。",
 *     species: "dog",
 *     size: "small",
 *   });
 */

export type TriageQueryRequest = {
  question: string;
  species?: "dog" | "cat" | "unknown" | string;
  size?: "small" | "large" | string;
  heart_rate_bpm?: number | null;
  crt_seconds?: number | null;
  rectal_temp_f?: number | null;
  rectal_temp_c?: number | null;
  top_k?: number;
  client_request_id?: string;
};

export type TriageSource = {
  rank?: number;
  score?: number;
  content?: string;
  content_zh?: string;
  chunk_type_zh?: string;
};

export type TriageQueryResponse = {
  api_version: string;
  request_id: string;
  record_id?: string | null;
  answer: string;
  answer_zh: string;
  answer_en: string;
  recommendation_zh?: string;
  recommendation_en?: string;
  intercepted: boolean;
  red_light_status?: "RED" | "YELLOW" | "GREEN" | string;
  sources: TriageSource[];
  model_used?: string;
  elapsed_ms?: number;
  extracted_symptoms?: string[];
};

export type AnimaAPIError = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
  };
};

export class AnimaTriageError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
    this.name = "AnimaTriageError";
  }
}

export function statusExplain(status?: string): { title: string; body: string } {
  switch (status) {
    case "RED":
      return {
        title: "红灯 = 紧急，先送医",
        body: "已出现危急信号。请立即送兽医急诊；系统已跳过 AI。",
      };
    case "YELLOW":
      return {
        title: "黄灯 = 需小心，持续观察",
        body: "有风险但尚未立即拦截。按建议处理；恶化则升级红灯送医。",
      };
    default:
      return {
        title: "绿灯 = 暂无紧急信号",
        body: "依目前描述未见红灯触发。不代表保证没事；有变化请重评。",
      };
  }
}

export class AnimaTriageClient {
  private baseUrl: string;
  private apiKey?: string;
  private fetchImpl: typeof fetch;

  constructor(opts: {
    baseUrl: string;
    apiKey?: string;
    fetchImpl?: typeof fetch;
  }) {
    this.baseUrl = opts.baseUrl.replace(/\/$/, "");
    this.apiKey = opts.apiKey;
    this.fetchImpl = opts.fetchImpl ?? fetch;
  }

  async health(): Promise<unknown> {
    const res = await this.fetchImpl(`${this.baseUrl}/health`);
    if (!res.ok) {
      throw new AnimaTriageError(`Health failed: HTTP ${res.status}`, res.status);
    }
    return res.json();
  }

  async query(body: TriageQueryRequest): Promise<TriageQueryResponse> {
    const requestId =
      body.client_request_id ??
      (globalThis.crypto?.randomUUID?.() ?? `app-${Date.now()}`);

    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "X-Request-Id": requestId,
    };
    if (this.apiKey) {
      headers["X-API-Key"] = this.apiKey;
    }

    const res = await this.fetchImpl(`${this.baseUrl}/v1/triage/query`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        ...body,
        client_request_id: requestId,
        top_k: body.top_k ?? 5,
      }),
    });

    const data = (await res.json()) as TriageQueryResponse & AnimaAPIError;
    if (!res.ok) {
      throw new AnimaTriageError(
        data.error?.message ?? `HTTP ${res.status}`,
        res.status,
        data.error?.code,
      );
    }
    return data;
  }
}
