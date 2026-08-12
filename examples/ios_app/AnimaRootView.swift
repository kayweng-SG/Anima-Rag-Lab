/**
 * AnimaLink iOS product shell (IA draft).
 *
 * Same target needs:
 *   AnimaTriageClient.swift, AnimaKeychain.swift
 * Replace smoke-only entry with: AnimaRootView()
 */

import SwiftUI

struct AnimaRootView: View {
    var body: some View {
        TabView {
            AnimaTriageHomeView()
                .tabItem { Label("分诊", systemImage: "cross.case") }
            AnimaHistoryPlaceholderView()
                .tabItem { Label("记录", systemImage: "list.bullet.rectangle") }
            AnimaSettingsView()
                .tabItem { Label("设置", systemImage: "gearshape") }
        }
    }
}

// MARK: - Home (first viewport)

struct AnimaTriageHomeView: View {
    @AppStorage("anima_base_url") private var baseURLString = ProcessInfo.processInfo.environment["ANIMA_BASE_URL"]
        ?? "http://127.0.0.1:8000"
    @State private var question = ""
    @State private var species = "dog"
    @State private var size = "small"
    @State private var loading = false
    @State private var errorText: String?
    @State private var result: TriageQueryResponse?

    private var client: AnimaTriageClient {
        AnimaTriageClient(baseURL: URL(string: baseURLString) ?? URL(string: "http://127.0.0.1:8000")!)
    }

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        Text("AnimaLink")
                            .font(.largeTitle.weight(.bold))
                        Text("紧急分诊辅助：先规则拦截危急信号，再给出可追溯建议。")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)

                        TextField("宠物怎么了？一句话描述情况", text: $question, axis: .vertical)
                            .lineLimit(3...5)
                            .padding(12)
                            .background(Color(.secondarySystemBackground))
                            .clipShape(RoundedRectangle(cornerRadius: 10))

                        HStack {
                            Picker("物种", selection: $species) {
                                Text("犬").tag("dog")
                                Text("猫").tag("cat")
                            }
                            Picker("体型", selection: $size) {
                                Text("小型").tag("small")
                                Text("大型").tag("large")
                            }
                        }

                        if let errorText {
                            Text(errorText)
                                .font(.footnote)
                                .foregroundStyle(.red)
                        }

                        Button {
                            Task { await submit() }
                        } label: {
                            Text(loading ? "分诊中…" : "开始分诊")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(loading || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                    }
                    .padding(20)
                }

                Text(TriageScreenModel.defaultDisclaimer)
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .frame(maxWidth: .infinity)
                    .background(.bar)
            }
            .navigationBarTitleDisplayMode(.inline)
            .navigationDestination(item: $result) { response in
                AnimaResultView(response: response)
            }
        }
    }

    @MainActor
    private func submit() async {
        loading = true
        errorText = nil
        defer { loading = false }
        do {
            result = try await client.query(
                TriageQueryRequest(question: question, species: species, size: size)
            )
        } catch {
            errorText = (error as? AnimaTriageError)?.userMessageZh ?? error.localizedDescription
        }
    }
}

// MARK: - Result

struct AnimaResultView: View {
    let response: TriageQueryResponse

    var body: some View {
        let ui = response.screen
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                if ui.showEmergencyBanner {
                    Text("请立即送兽医急诊")
                        .font(.title3.weight(.semibold))
                        .foregroundStyle(.red)
                }
                Text(ui.badge).font(.headline)
                Text(ui.explain.title)
                Text(ui.explain.body).font(.footnote).foregroundStyle(.secondary)
                if ui.showInterceptedHint {
                    Text("已拦截 · 跳过 LLM").foregroundStyle(.red)
                }
                if !ui.symptomChips.isEmpty {
                    Text(ui.symptomChips.joined(separator: " · "))
                        .font(.footnote)
                }
                Divider()
                Text(ui.answerZh)
                if ui.showSourcesAsAdvice, !response.sources.isEmpty {
                    Text("参考来源 \(response.sources.count) 条")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(20)
        }
        .navigationTitle("分诊结果")
        .safeAreaInset(edge: .bottom) {
            Text(ui.disclaimer)
                .font(.caption2)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
                .padding()
                .frame(maxWidth: .infinity)
                .background(.bar)
        }
    }
}

// MARK: - History / Settings placeholders

struct AnimaHistoryPlaceholderView: View {
    var body: some View {
        NavigationStack {
            ContentUnavailableView(
                "分诊记录",
                systemImage: "list.bullet.rectangle",
                description: Text("M2：接入 GET /v1/triage/results 列出 record_id 与灯号。")
            )
            .navigationTitle("记录")
        }
    }
}

struct AnimaSettingsView: View {
    @AppStorage("anima_base_url") private var baseURL = ProcessInfo.processInfo.environment["ANIMA_BASE_URL"]
        ?? "http://127.0.0.1:8000"
    @State private var apiKeyDraft = AnimaKeychain.apiKey() ?? ""
    @State private var hint: String?
    @State private var healthLine = "—"

    var body: some View {
        NavigationStack {
            Form {
                Section("服务") {
                    TextField("Base URL", text: $baseURL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                    Button("检查 /health") { Task { await ping() } }
                    Text(healthLine).font(.footnote).foregroundStyle(.secondary)
                }
                Section("API Key") {
                    SecureField("ANIMA_API_KEY", text: $apiKeyDraft)
                    Button("保存到 Keychain") {
                        _ = AnimaKeychain.setAPIKey(apiKeyDraft)
                        hint = "已保存"
                    }
                    if let hint { Text(hint).font(.caption) }
                }
            }
            .navigationTitle("设置")
        }
    }

    @MainActor
    private func ping() async {
        guard let url = URL(string: baseURL) else {
            healthLine = AnimaTriageError.invalidURL.userMessageZh
            return
        }
        do {
            let h = try await AnimaTriageClient(baseURL: url).health()
            healthLine = "status=\(h["status"] ?? "?") auth=\(h["auth_required"] ?? false)"
        } catch {
            healthLine = (error as? AnimaTriageError)?.userMessageZh ?? error.localizedDescription
        }
    }
}

extension TriageQueryResponse: Hashable {
    public func hash(into hasher: inout Hasher) {
        hasher.combine(requestId)
        hasher.combine(recordId)
    }

    public static func == (lhs: TriageQueryResponse, rhs: TriageQueryResponse) -> Bool {
        lhs.requestId == rhs.requestId && lhs.recordId == rhs.recordId
    }
}

#if DEBUG
struct AnimaRootView_Previews: PreviewProvider {
    static var previews: some View {
        AnimaRootView()
    }
}
#endif
