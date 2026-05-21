import Foundation

// Input envelope. `action` selects the operation; absent ⇒ "write" (backward compat).
struct Request: Decodable {
    let action: String?
    // write
    let quantities: [QuantitySample]?
    let sleepStages: [SleepStageSample]?
    // query-sleep
    let start: Date?
    let end: Date?
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
    // "awake" | "light" | "rem" | "deep" | "inBed" | "asleep"
    let stage: String
    let startDate: Date
    let endDate: Date
    let externalUUID: String
}

// Output envelope. Only fields relevant to the action are populated.
struct Response: Encodable {
    let status: String
    let code: Int?
    let message: String?
    // write
    let written: Int?
    let skipped: Int?
    // query-sleep
    let sleepSamples: [SleepSampleOut]?
}

struct SleepSampleOut: Encodable {
    let startDate: Date
    let endDate: Date
    let value: String       // "inBed" | "asleep" | "awake" | "asleepCore" | "asleepDeep" | "asleepREM" | "unknown"
    let sourceName: String  // e.g. "Apple Watch", "HealthSyncWriter"
}
