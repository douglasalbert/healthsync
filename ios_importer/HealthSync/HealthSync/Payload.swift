import Foundation

// Mirrors the JSON format written by `healthsync export` on the Mac.

struct ExportPayload: Decodable {
    let version: Int
    let exportedAt: String
    let periodStart: String
    let periodEnd: String
    let quantities: [QuantitySample]
    let sleepStages: [SleepStageSample]
}

struct QuantitySample: Decodable {
    let typeIdentifier: String
    let value: Double
    let unit: String
    let startDate: String
    let endDate: String
    let externalUUID: String
    let sourceMetadata: [String: String]?
}

struct SleepStageSample: Decodable {
    let stage: String
    let startDate: String
    let endDate: String
    let externalUUID: String
}
