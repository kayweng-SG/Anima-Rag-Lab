/**
 * AnimaLink triage client (iOS / Swift)
 *
 * Drop into an Xcode app target. Uses URLSession + Codable only (no extra deps).
 *
 * Usage:
 *   let client = AnimaTriageClient(
 *     baseURL: URL(string: "http://127.0.0.1:8000")!,
 *     apiKey: ProcessInfo.processInfo.environment["ANIMA_API_KEY"] // nil in local demo
 *   )
 *   let result = try await client.query(
 *     TriageQueryRequest(question: "小狗吃了巧克力，精神还行，有点担心。", species: "dog", size: "small")
 *   )
 *   // Switch on result.redLightStatus: RED / YELLOW / GREEN
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
        switch redLightStatus {
        case "RED":
            return ("红灯 = 紧急，先送医", "已出现危急信号。请立即送兽医急诊；系统已跳过 AI。")
        case "YELLOW":
            return ("黄灯 = 需小心，持续观察", "有风险但尚未立即拦截。按建议处理；恶化则升级红灯送医。")
        default:
            return ("绿灯 = 暂无紧急信号", "依目前描述未见红灯触发。不代表保证没事；有变化请重评。")
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
    case http(status: Int, code: String?, message: String)
    case decoding(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid Anima API URL"
        case let .http(_, code, message):
            return code.map { "[\($0)] \(message)" } ?? message
        case let .decoding(err):
            return "Decode failed: \(err.localizedDescription)"
        }
    }
}

// MARK: - Client

final class AnimaTriageClient {
    private let baseURL: URL
    private let apiKey: String?
    private let session: URLSession
    private let decoder: JSONDecoder
    private let encoder: JSONEncoder

    init(baseURL: URL, apiKey: String? = nil, session: URLSession = .shared) {
        self.baseURL = baseURL
        self.apiKey = apiKey
        self.session = session
        self.decoder = JSONDecoder()
        self.encoder = JSONEncoder()
    }

    /// `GET /health` — public, no API key.
    func health() async throws -> [String: Any] {
        let url = baseURL.appendingPathComponent("health")
        let (data, response) = try await session.data(from: url)
        try Self.throwIfNeeded(data: data, response: response)
        return (try JSONSerialization.jsonObject(with: data) as? [String: Any]) ?? [:]
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

        let (data, response) = try await session.data(for: request)
        try Self.throwIfNeeded(data: data, response: response)
        do {
            return try decoder.decode(TriageQueryResponse.self, from: data)
        } catch {
            throw AnimaTriageError.decoding(error)
        }
    }

    private static func throwIfNeeded(data: Data, response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else { return }
        guard !(200...299).contains(http.statusCode) else { return }
        if let body = try? JSONDecoder().decode(AnimaAPIErrorBody.self, from: data),
           let message = body.error?.message {
            throw AnimaTriageError.http(
                status: http.statusCode,
                code: body.error?.code,
                message: message
            )
        }
        let raw = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
        throw AnimaTriageError.http(status: http.statusCode, code: nil, message: raw)
    }
}

/*
 // MARK: - Minimal SwiftUI wiring (optional)

 import SwiftUI

 struct TriageDemoView: View {
     @State private var question = "小狗吃了巧克力，精神还行，有点担心。"
     @State private var result: TriageQueryResponse?
     @State private var errorText: String?
     @State private var loading = false

     private let client = AnimaTriageClient(
         baseURL: URL(string: "http://127.0.0.1:8000")!
     )

     var body: some View {
         Form {
             TextField("情况描述", text: $question, axis: .vertical)
             Button("开始分诊") { Task { await run() } }
                 .disabled(loading || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
             if let result {
                 Text(result.statusExplain.title).bold()
                 Text(result.answerZh)
                 if result.intercepted {
                     Text("已拦截 · 跳过 LLM").foregroundStyle(.red)
                 }
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
