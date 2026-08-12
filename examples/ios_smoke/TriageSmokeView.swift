/**
 * Minimal SwiftUI smoke screen for AnimaLink triage (iOS).
 *
 * Requires AnimaTriageClient.swift in the same target.
 * Set Scheme env: ANIMA_BASE_URL, ANIMA_API_KEY
 */

import SwiftUI

struct TriageSmokeView: View {
    let client: AnimaTriageClient

    @State private var question = "小狗吃了巧克力，精神还行，有点担心。"
    @State private var species = "dog"
    @State private var size = "small"
    @State private var result: TriageQueryResponse?
    @State private var errorText: String?
    @State private var loading = false
    @State private var healthLine = "未检查"

    private let presets: [(title: String, question: String, size: String)] = [
        ("黄灯 · 巧克力", "小狗吃了巧克力，精神还行，有点担心。", "small"),
        ("红灯 · 中毒", "狗狗中毒怎么办？刚才吃了老鼠药，还在呕吐。", "small"),
        ("绿灯 · 心率", "小狗正常心率是多少？运动后呼吸有点快，有点担心。", "small"),
        ("黄灯 · 中暑轻", "中暑怎么办？散步后喘气、流口水，仍清醒能走。", "large"),
    ]

    var body: some View {
        NavigationStack {
            Form {
                Section("连接") {
                    Text(healthLine).font(.footnote)
                    Button("检查 /health") { Task { await pingHealth() } }
                }

                Section("主诉") {
                    TextField("情况描述", text: $question, axis: .vertical)
                        .lineLimit(3...6)
                    Picker("物种", selection: $species) {
                        Text("犬").tag("dog")
                        Text("猫").tag("cat")
                    }
                    Picker("体型", selection: $size) {
                        Text("小型").tag("small")
                        Text("大型").tag("large")
                    }
                }

                Section("示例") {
                    ForEach(presets, id: \.title) { item in
                        Button(item.title) {
                            question = item.question
                            size = item.size
                        }
                    }
                }

                Section {
                    Button(loading ? "分诊中…" : "开始分诊") {
                        Task { await runTriage() }
                    }
                    .disabled(loading || question.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }

                if let ui = result?.screen {
                    Section("灯号") {
                        if ui.showEmergencyBanner {
                            Text("请立即送兽医急诊")
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
                            Text(ui.symptomChips.joined(separator: " · "))
                                .font(.footnote)
                        }
                    }
                    Section("结论") {
                        Text(ui.answerZh)
                        if ui.showSourcesAsAdvice, let n = result?.sources.count, n > 0 {
                            Text("参考来源 \(n) 条").font(.caption)
                        } else if !ui.showSourcesAsAdvice {
                            Text("红灯：不展示 sources 作为护理建议").font(.caption).foregroundStyle(.secondary)
                        }
                        Text(ui.disclaimer).font(.caption2).foregroundStyle(.secondary)
                    }
                }

                if let errorText {
                    Section {
                        Text(errorText).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("AnimaLink 冒烟")
            .task { await pingHealth() }
        }
    }

    @MainActor
    private func pingHealth() async {
        do {
            let h = try await client.health()
            let auth = h["auth_required"] as? Bool ?? false
            let status = h["status"] as? String ?? "?"
            healthLine = "status=\(status) auth_required=\(auth)"
            errorText = nil
        } catch {
            healthLine = "health 失败"
            errorText = error.localizedDescription
        }
    }

    @MainActor
    private func runTriage() async {
        loading = true
        errorText = nil
        defer { loading = false }
        do {
            var req = TriageQueryRequest(question: question, species: species, size: size)
            if question.contains("心率") {
                req.heartRateBpm = 95
                req.crtSeconds = 1.5
                req.rectalTempF = 101.8
            }
            if question.contains("中暑") && question.contains("清醒") {
                req.heartRateBpm = 120
                req.crtSeconds = 1.5
                req.rectalTempF = 102.8
            }
            result = try await client.query(req)
        } catch {
            result = nil
            errorText = error.localizedDescription
        }
    }
}

#if DEBUG
struct TriageSmokeView_Previews: PreviewProvider {
    static var previews: some View {
        TriageSmokeView(
            client: AnimaTriageClient(baseURL: URL(string: "http://127.0.0.1:8000")!)
        )
    }
}
#endif
