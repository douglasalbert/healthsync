import Foundation
import HealthKit

func emit(_ response: Response) -> Never {
    let encoder = JSONEncoder()
    encoder.dateEncodingStrategy = .iso8601
    let data = (try? encoder.encode(response)) ?? Data()
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
    exit(response.status == "ok" ? 0 : 1)
}

func emitError(code: Int, message: String) -> Never {
    emit(Response(
        status: "error",
        code: code,
        message: message,
        written: nil,
        skipped: nil,
        sleepSamples: nil
    ))
}

// Read all of stdin
var inputData = Data()
let stdin = FileHandle.standardInput
while true {
    let chunk = stdin.availableData
    if chunk.isEmpty { break }
    inputData.append(chunk)
}

let decoder = JSONDecoder()
decoder.dateDecodingStrategy = .iso8601

let request: Request
do {
    request = try decoder.decode(Request.self, from: inputData)
} catch {
    emitError(code: -1, message: "JSON decode failed: \(error.localizedDescription)")
}

let writer = HKWriter()
let action = request.action ?? "write"

switch action {

case "write":
    let quantities = request.quantities ?? []
    let sleepStages = request.sleepStages ?? []

    do {
        try writer.requestWriteAuthorization(quantities: quantities, hasSleep: !sleepStages.isEmpty)
    } catch HKWriterError.unavailable {
        emitError(code: -2, message: "HealthKit is not available on this device.")
    } catch let error as HKError {
        emitError(code: error.errorCode, message: error.localizedDescription)
    } catch {
        emitError(code: -3, message: "Authorization error: \(error.localizedDescription)")
    }

    let (written, skipped) = writer.write(quantities: quantities, sleepStages: sleepStages)
    emit(Response(
        status: "ok",
        code: nil,
        message: nil,
        written: written,
        skipped: skipped,
        sleepSamples: nil
    ))

case "query-sleep":
    guard let start = request.start, let end = request.end else {
        emitError(code: -1, message: "query-sleep requires `start` and `end` ISO8601 dates")
    }

    do {
        try writer.requestSleepReadAuthorization()
    } catch HKWriterError.unavailable {
        emitError(code: -2, message: "HealthKit is not available on this device.")
    } catch let error as HKError {
        emitError(code: error.errorCode, message: error.localizedDescription)
    } catch {
        emitError(code: -3, message: "Authorization error: \(error.localizedDescription)")
    }

    do {
        let samples = try writer.querySleep(start: start, end: end)
        emit(Response(
            status: "ok",
            code: nil,
            message: nil,
            written: nil,
            skipped: nil,
            sleepSamples: samples
        ))
    } catch let error as HKError {
        emitError(code: error.errorCode, message: error.localizedDescription)
    } catch {
        emitError(code: -3, message: "Query failed: \(error.localizedDescription)")
    }

default:
    emitError(code: -1, message: "unknown action: \(action)")
}
