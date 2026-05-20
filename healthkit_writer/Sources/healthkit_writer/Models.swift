import Foundation

struct Payload: Decodable {
    let quantities: [QuantitySample]
    let sleepStages: [SleepStageSample]
}

struct QuantitySample: Decodable {
    let typeIdentifier: String
    let value: Double
    let unit: String
    let startDate: Date
    let endDate: Date
    let externalUUID: String
    let sourceMetadata: [String: String]?
}

struct SleepStageSample: Decodable {
    let stage: String   // "awake" | "light" | "rem" | "deep"
    let startDate: Date
    let endDate: Date
    let externalUUID: String
}

struct WriteResponse: Encodable {
    let status: String
    let written: Int
    let skipped: Int
    let code: Int?
    let message: String?
}
