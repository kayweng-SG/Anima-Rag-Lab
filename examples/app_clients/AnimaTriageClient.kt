/**
 * AnimaLink triage client (Android / Kotlin)
 *
 * Copy into an Android module. Uses OkHttp + kotlinx.serialization.
 *
 * Gradle (module):
 *   implementation("com.squareup.okhttp3:okhttp:4.12.0")
 *   implementation("org.jetbrains.kotlinx:kotlinx-serialization-json:1.6.3")
 *   // plugins { id("org.jetbrains.kotlin.plugin.serialization") }
 *
 * Usage:
 *   val client = AnimaTriageClient(
 *       baseUrl = "http://10.0.2.2:8000", // emulator → host machine
 *       apiKey = null,                     // or BuildConfig.ANIMA_API_KEY
 *   )
 *   val result = client.query(
 *       TriageQueryRequest(
 *           question = "小狗吃了巧克力，精神还行，有点担心。",
 *           species = "dog",
 *           size = "small",
 *       )
 *   )
 *   // when (result.redLightStatus) { "RED" -> … }
 */

package com.animalink.triage.sample

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.encodeToString
import kotlinx.serialization.json.Json
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.UUID
import java.util.concurrent.TimeUnit

// MARK: - Models

@Serializable
data class TriageQueryRequest(
    val question: String,
    val species: String? = null,
    val size: String? = null,
    @SerialName("heart_rate_bpm") val heartRateBpm: Double? = null,
    @SerialName("crt_seconds") val crtSeconds: Double? = null,
    @SerialName("rectal_temp_f") val rectalTempF: Double? = null,
    @SerialName("rectal_temp_c") val rectalTempC: Double? = null,
    @SerialName("top_k") val topK: Int = 5,
    @SerialName("client_request_id") val clientRequestId: String? = null,
)

@Serializable
data class TriageSource(
    val rank: Int? = null,
    val score: Double? = null,
    val content: String? = null,
    @SerialName("content_zh") val contentZh: String? = null,
    @SerialName("chunk_type_zh") val chunkTypeZh: String? = null,
)

@Serializable
data class TriageQueryResponse(
    @SerialName("api_version") val apiVersion: String,
    @SerialName("request_id") val requestId: String,
    @SerialName("record_id") val recordId: String? = null,
    val answer: String,
    @SerialName("answer_zh") val answerZh: String,
    @SerialName("answer_en") val answerEn: String,
    @SerialName("recommendation_zh") val recommendationZh: String? = null,
    @SerialName("recommendation_en") val recommendationEn: String? = null,
    val intercepted: Boolean,
    @SerialName("red_light_status") val redLightStatus: String? = null,
    val sources: List<TriageSource> = emptyList(),
    @SerialName("model_used") val modelUsed: String? = null,
    @SerialName("elapsed_ms") val elapsedMs: Double? = null,
    @SerialName("extracted_symptoms") val extractedSymptoms: List<String> = emptyList(),
) {
    /** Human-readable traffic-light copy for App UI. */
    fun statusExplain(): Pair<String, String> = when (redLightStatus) {
        "RED" -> "红灯 = 紧急，先送医" to
            "已出现危急信号。请立即送兽医急诊；系统已跳过 AI。"
        "YELLOW" -> "黄灯 = 需小心，持续观察" to
            "有风险但尚未立即拦截。按建议处理；恶化则升级红灯送医。"
        else -> "绿灯 = 暂无紧急信号" to
            "依目前描述未见红灯触发。不代表保证没事；有变化请重评。"
    }
}

@Serializable
data class AnimaAPIErrorBody(
    val error: ErrorPayload? = null,
) {
    @Serializable
    data class ErrorPayload(
        val code: String? = null,
        val message: String? = null,
        @SerialName("request_id") val requestId: String? = null,
    )
}

class AnimaTriageException(
    val httpStatus: Int,
    val code: String?,
    override val message: String,
) : Exception(message)

// MARK: - Client

class AnimaTriageClient(
    baseUrl: String,
    private val apiKey: String? = null,
    private val http: OkHttpClient = OkHttpClient.Builder()
        .connectTimeout(15, TimeUnit.SECONDS)
        .readTimeout(90, TimeUnit.SECONDS)
        .build(),
    private val json: Json = Json {
        ignoreUnknownKeys = true
        encodeDefaults = false
    },
) {
    private val root = baseUrl.trimEnd('/')
    private val mediaJson = "application/json; charset=utf-8".toMediaType()

    /** GET /health — public. */
    fun health(): String {
        val request = Request.Builder().url("$root/health").get().build()
        http.newCall(request).execute().use { resp ->
            val body = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                throw AnimaTriageException(resp.code, null, body.ifBlank { "HTTP ${resp.code}" })
            }
            return body
        }
    }

    /** POST /v1/triage/query */
    fun query(body: TriageQueryRequest): TriageQueryResponse {
        val requestId = body.clientRequestId ?: UUID.randomUUID().toString()
        val payload = if (body.clientRequestId == null) {
            body.copy(clientRequestId = requestId)
        } else {
            body
        }

        val builder = Request.Builder()
            .url("$root/v1/triage/query")
            .addHeader("Content-Type", "application/json")
            .addHeader("X-Request-Id", requestId)
            .post(json.encodeToString(payload).toRequestBody(mediaJson))

        if (!apiKey.isNullOrBlank()) {
            builder.addHeader("X-API-Key", apiKey)
        }

        http.newCall(builder.build()).execute().use { resp ->
            val raw = resp.body?.string().orEmpty()
            if (!resp.isSuccessful) {
                val parsed = runCatching { json.decodeFromString<AnimaAPIErrorBody>(raw) }.getOrNull()
                throw AnimaTriageException(
                    httpStatus = resp.code,
                    code = parsed?.error?.code,
                    message = parsed?.error?.message
                        ?: raw.ifBlank { "HTTP ${resp.code}" },
                )
            }
            return json.decodeFromString(raw)
        }
    }
}

/*
 // Coroutine wrapper example:

 // suspend fun queryAsync(body: TriageQueryRequest): TriageQueryResponse =
 //     withContext(Dispatchers.IO) { query(body) }
 //
 // Emulator base URL: http://10.0.2.2:8000
 // Physical device:   http://<your-lan-ip>:8000  (and ANIMA_API_HOST=0.0.0.0)
 */
