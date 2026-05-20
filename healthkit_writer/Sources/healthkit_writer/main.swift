import Foundation
import HealthKit

func respond(_ response: WriteResponse) -> Never {
    let encoder = JSONEncoder()
    let data = (try? encoder.encode(response)) ?? Data()
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(response.status == "ok" ? 0 : 1)
}

// Read all of stdin
var inputData = Data()
let stdin = FileHandle.standardInput
while true {
    let chunk = stdin.availableData
    if chunk.isEmpty { break }
    inputData.append(chunk)
}

// Decode payload
let decoder = JSONDecoder()
decoder.dateDecodingStrategy = .iso8601

let payload: Payload
do {
    payload = try decoder.decode(Payload.self, from: inputData)
} catch {
    respond(WriteResponse(
        status: "error",
        written: 0,
        skipped: 0,
        code: -1,
        message: "JSON decode failed: \(error.localizedDescription)"
    ))
}

let writer = HKWriter()

// Request HealthKit authorization
do {
    try writer.requestAuthorization(for: payload)
} catch HKWriterError.unavailable {
    respond(WriteResponse(
        status: "error",
        written: 0,
        skipped: 0,
        code: -2,
        message: "HealthKit is not available on this device."
    ))
} catch let error as HKError {
    respond(WriteResponse(
        status: "error",
        written: 0,
        skipped: 0,
        code: error.errorCode,
        message: error.localizedDescription
    ))
} catch {
    respond(WriteResponse(
        status: "error",
        written: 0,
        skipped: 0,
        code: -3,
        message: "Authorization error: \(error.localizedDescription)"
    ))
}

// Write samples
let (written, skipped) = writer.write(payload: payload)

respond(WriteResponse(
    status: "ok",
    written: written,
    skipped: skipped,
    code: nil,
    message: nil
))
