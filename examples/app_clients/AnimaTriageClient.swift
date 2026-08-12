/**
 * AnimaLink triage client (iOS / Swift)
 *
 * Drop into an Xcode app target. Uses URLSession + Codable only (no extra deps).
 *
 * Usage:
 *   AnimaKeychain.setAPIKey("…")  // once; or pass apiKey:
 *   let client = AnimaTriageClient(
 *     baseURL: URL(string: "http://127.0.0.1:8000")!
 *   )
 *   // On failure: (error as? AnimaTriageError)?.userMessageZh
 *   let result = try await client.query(
 *     TriageQueryRequest(question: "小狗吃了巧克力，精神还行，有点担心。", species: "dog", size: "small")
 *   )
 *   // result.screen → TriageScreenModel (banner / sources / disclaimer)
 */

import Foundation

// MARK: - Request / Response

struct TriageQueryRequest: Encodable {
    var question: String
    var species: String? = nil          // dog | cat | unknown
    var size: String? = nil             // small | large
    var heartRateBpm: Double? = nil
    var crtSeconds: Double? = nil
    var rectalTempF: Double? = nil
    var rectalTempC: Double? = nil
    var topK: Int = 5
    var clientRequestId: String? = nil

    enum CodingKeys: String, CodingKey {
        case question, species, size
        case heartRateBpm = "heart_rate_bpm"
        case crtSeconds = "crt_seconds"
        case rectalTempF = "rectal_temp_f"
        case rectalTempC = "rectal_temp_c"
        case topK = "top_k"
        case clientRequestId = "client_request_id"
    }
}

struct TriageSource: Decodable {
    var rank: Int?
    var score: Double?
    var content: String?
    var contentZh: String?
    var chunkTypeZh: String?

    enum CodingKeys: String, CodingKey {
        case rank, score, content
        case contentZh = "content_zh"
        case chunkTypeZh = "chunk_type_zh"
    }
}

struct TriageQueryResponse: Decodable {
    var apiVersion: String
    var requestId: String
    var recordId: String?
    var answer: String
    var answerZh: String
    var answerEn: String
    var recommendationZh: String?
    var recommendationEn: String?
    var intercepted: Bool
    var redLightStatus: String?   // RED | YELLOW | GREEN
    var sources: [TriageSource]
    var modelUsed: String?
    var elapsedMs: Double?
    var extractedSymptoms: [String]

    enum CodingKeys: String, CodingKey {
        case answer, intercepted, sources
        case apiVersion = "api_version"
        case requestId = "request_id"
        case recordId = "record_id"
        case answerZh = "answer_zh"
        case answerEn = "answer_en"
        case recommendationZh = "recommendation_zh"
        case recommendationEn = "recommendation_en"
        case redLightStatus = "red_light_status"
        case modelUsed = "model_used"
        case elapsedMs = "elapsed_ms"
        case extractedSymptoms = "extracted_symptoms"
    }

    /// Human-readable traffic-light copy for App UI.
    var statusExplain: (title: String, body: String) {
        TriageScreenModel.map(self).explain
    }

    /// Canonical App presentation flags — prefer this over ad-hoc `if intercepted`.
    var screen: TriageScreenModel { TriageScreenModel.map(self) }
}

/// How the App should render one triage result (step 2: traffic-light UI mapping).
struct TriageScreenModel {
    enum Tone: String {
        case red, yellow, green
    }

    let tone: Tone
    let badge: String                 // e.g. "黄灯 YELLOW"
    let explain: (title: String, body: String)
    let showEmergencyBanner: Bool     // RED only
    let showInterceptedHint: Bool     // "已拦截 · 跳过 LLM"
    /// When false, do **not** present `sources` as care advice (RED).
    let showSourcesAsAdvice: Bool
    let answerZh: String
    let recommendationZh: String?
    let symptomChips: [String]
    let disclaimer: String

    static let defaultDisclaimer = "不能替代执业兽医诊断与治疗。紧急情况请立即送医。"

    static func map(_ r: TriageQueryResponse) -> TriageScreenModel {
        let status = (r.redLightStatus ?? "GREEN").uppercased()
        switch status {
        case "RED":
            return TriageScreenModel(
                tone: .red,
                badge: "红灯 RED",
                explain: (
                    "红灯 = 紧急，先送医",
                    "已出现危急信号。请立即送兽医急诊；系统已跳过 AI。"
                ),
                showEmergencyBanner: true,
                showInterceptedHint: r.intercepted,
                showSourcesAsAdvice: false,
                answerZh: r.answerZh,
                recommendationZh: r.recommendationZh,
                symptomChips: r.extractedSymptoms,
                disclaimer: defaultDisclaimer
            )
        case "YELLOW":
            return TriageScreenModel(
                tone: .yellow,
                badge: "黄灯 YELLOW",
                explain: (
                    "黄灯 = 需小心，持续观察",
                    "有风险但尚未立即拦截。按建议处理；恶化则升级红灯送医。"
                ),
                showEmergencyBanner: false,
                showInterceptedHint: false,
                showSourcesAsAdvice: true,
                answerZh: r.answerZh,
                recommendationZh: r.recommendationZh,
                symptomChips: r.extractedSymptoms,
                disclaimer: defaultDisclaimer
            )
        default:
            return TriageScreenModel(
                tone: .green,
                badge: "绿灯 GREEN",
                explain: (
                    "绿灯 = 暂无紧急信号",
                    "依目前描述未见红灯触发。不代表保证没事；有变化请重评。"
                ),
                showEmergencyBanner: false,
                showInterceptedHint: false,
                showSourcesAsAdvice: true,
                answerZh: r.answerZh,
                recommendationZh: r.recommendationZh,
                symptomChips: r.extractedSymptoms,
                disclaimer: defaultDisclaimer
            )
        }
    }
}

struct AnimaAPIErrorBody: Decodable {
    struct ErrorPayload: Decodable {
        var code: String?
        var message: String?
        var requestId: String?

        enum CodingKeys: String, CodingKey {
            case code, message
            case requestId = "request_id"
        }
    }

    var error: ErrorPayload?
}

enum AnimaTriageError: Error, LocalizedError {
    case invalidURL
    case unauthorized(message: String)
    case timeout
    case offline
    case http(status: Int, code: String?, message: String)
    case decoding(Error)
    case transport(Error)

    /// Fixed product copy for Chinese App UI (prefer over `localizedDescription` in views).
    var userMessageZh: String {
        switch self {
        case .invalidURL:
            return "服务地址无效，请检查 Base URL。"
        case .unauthorized:
            return "API Key 无效或未填写。请在设置中写入与服务器一致的密钥。"
        case .timeout:
            return "请求超时。请确认手机与 Mac/服务器同一网络后重试。"
        case .offline:
            return "网络不可用。请检查 Wi‑Fi / 蜂窝网络后重试。"
        case let .http(status, code, message):
            if status == 401 || code == "unauthorized" {
                return "API Key 无效或未填写。请在设置中写入与服务器一致的密钥。"
            }
            if status == 503 || code == "service_unavailable" {
                return "服务暂时不可用（向量库或模型未就绪），请稍后重试。"
            }
            if status == 422 || code == "validation_error" {
                return "输入有误：\(message)"
            }
            return "请求失败（HTTP \(status)）：\(message)"
        case .decoding:
            return "服务器返回无法解析，请稍后重试或升级 App。"
        case let .transport(err):
            return "网络错误：\(err.localizedDescription)"
        }
    }

    var errorDescription: String? { userMessageZh }

    static func mapTransport(_ error: Error) -> AnimaTriageError {
        let ns = error as NSError
        if let urlErr = error as? URLError {
            switch urlErr.code {
            case .timedOut:
                return .timeout
            case .notConnectedToInternet, .networkConnectionLost, .dataNotAllowed:
                return .offline
            case .cannotFindHost, .cannotConnectToHost, .dnsLookupFailed:
                return .offline
            default:
                break
            }
        }
        if ns.domain == NSURLErrorDomain && ns.code == NSURLErrorTimedOut {
            return .timeout
        }
        return .transport(error)
    }
}

// MARK: - Client

final class AnimaTriageClient {
    private let baseURL: URL
    private let apiKey: String?
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    /// - Parameters:
    ///   - apiKey: If nil, resolves from Keychain then `ANIMA_API_KEY` env.
    ///   - timeoutSeconds: Request timeout (LLM answers can be slow; default 90s).
    init(
        baseURL: URL,
        apiKey: String? = nil,
        timeoutSeconds: TimeInterval = 90,
        session: URLSession? = nil
    ) {
        self.baseURL = baseURL
        self.apiKey = AnimaKeychain.resolveAPIKey(explicit: apiKey)
        if let session {
            self.session = session
        } else {
            let config = URLSessionConfiguration.ephemeral
            config.timeoutIntervalForRequest = timeoutSeconds
            config.timeoutIntervalForResource = timeoutSeconds + 30
            config.waitsForConnectivity = true
            self.session = URLSession(configuration: config)
        }
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    /// Rebuild client after Keychain save (same base URL, refreshed key).
    func withResolvedAPIKey() -> AnimaTriageClient {
        AnimaTriageClient(baseURL: baseURL, apiKey: AnimaKeychain.resolveAPIKey())
    }

    /// `GET /health` — public, no API key.
    func health() async throws -> [String: Any] {
        let url = baseURL.appendingPathComponent("health")
        do {
            let (data, response) = try await session.data(from: url)
            try Self.throwIfNeeded(data: data, response: response)
            return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
        } catch let err as AnimaTriageError {
            throw err
        } catch {
            throw AnimaTriageError.mapTransport(error)
        }
    }

    /// `POST /v1/triage/query`
    func query(_ body: TriageQueryRequest) async throws -> TriageQueryResponse {
        let url = baseURL.appendingPathComponent("v1/triage/query")
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let apiKey, !apiKey.isEmpty {
            request.setValue(apiKey, forHTTPHeaderField: "X-API-Key")
        }
        let requestId = body.clientRequestId ?? UUID().uuidString
        request.setValue(requestId, forHTTPHeaderField: "X-Request-Id")

        var payload = body
        if payload.clientRequestId == nil {
            payload.clientRequestId = requestId
        }
        request.httpBody = try encoder.encode(payload)

        do {
            let (data, response) = try await session.data(for: request)
            try Self.throwIfNeeded(data: data, response: response)
            do {
                return try decoder.decode(TriageQueryResponse.self, from: data)
            } catch {
                throw AnimaTriageError.decoding(error)
            }
        } catch let err as AnimaTriageError {
            throw err
        } catch {
            throw AnimaTriageError.mapTransport(error)
        }
    }

    private static func throwIfNeeded(data: Data, response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard !(200...299).contains(http.statusCode) else { return }
        if let body = try? JSONDecoder().decode(AnimaAPIErrorBody.self, from: data) {
            let code = body.error?.code
            let message = body.error?.message ?? "HTTP \(http.statusCode)"
            if http.statusCode == 401 || code == "unauthorized" {
                throw AnimaTriageError.unauthorized(message: message)
            }
            throw AnimaTriageError.http(status: http.statusCode, code: code, message: message)
        }
        let raw = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
        if http.statusCode == 401 {
            throw AnimaTriageError.unauthorized(message: raw)
        }
        throw AnimaTriageError.http(status: http.statusCode, code: nil, message: raw)
    }
}

/*
 // MARK: - Minimal SwiftUI wiring (optional) — uses TriageScreenModel

 import SwiftUI

 struct TriageDemoView: View {
     @State private var question = "小狗吃了巧克力，精神还行，有点担心。"
     @State private var result: TriageQueryResponse?
     @State private var errorText: String?
     @State private var loading = false

     // Simulator: 127.0.0.1 · Device: http://<Mac-LAN-IP>:8000
     private let client = AnimaTriageClient(
         baseURL: URL(string: "http://127.0.0.1:8000")!
     )

     var body: some View {
         Form {
             TextField("情况描述", text: $question, axis: .vertical)
             Button("开始分诊") { Task { await run() } }
                 .disabled(loading || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)

             if let ui = result?.screen {
                 if ui.showEmergencyBanner {
                     Text("⚠︎ 请立即送兽医急诊")
                         .font(.headline)
                         .foregroundStyle(.red)
                 }
                 Text(ui.badge).bold()
                 Text(ui.explain.title)
                 Text(ui.explain.body).font(.footnote)
                 if ui.showInterceptedHint {
                     Text("已拦截 · 跳过 LLM").foregroundStyle(.red)
                 }
                 if !ui.symptomChips.isEmpty {
                     Text("识别症状：\(ui.symptomChips.joined(separator: " · "))")
                         .font(.footnote)
                 }
                 Text(ui.answerZh)
                 // RED: never treat sources as care advice
                 if ui.showSourcesAsAdvice, let sources = result?.sources, !sources.isEmpty {
                     Text("参考来源 \(sources.count) 条").font(.caption)
                 }
                 Text(ui.disclaimer).font(.caption2).foregroundStyle(.secondary)
             }
             if let errorText { Text(errorText).foregroundStyle(.red) }
         }
     }

     @MainActor
     private func run() async {
         loading = true
         errorText = nil
         defer { loading = false }
         do {
             result = try await client.query(
                 TriageQueryRequest(question: question, species: "dog", size: "small")
             )
         } catch {
             errorText = error.localizedDescription
         }
     }
 }
 */
