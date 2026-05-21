import Foundation
import HealthKit
import Combine


struct ImportResult {
    var written: Int = 0
    var skipped: Int = 0
    var errors: [String] = []
}

@MainActor
class HKImporter: ObservableObject {
    private let store = HKHealthStore()

    @Published var status: String = "Ready"
    @Published var result: ImportResult?
    @Published var isRunning = false

    func requestAuthorization(for payload: ExportPayload) async throws {
        var writeTypes = Set<HKSampleType>()

        for q in payload.quantities {
            if let t = HKObjectType.quantityType(forIdentifier: HKQuantityTypeIdentifier(rawValue: q.typeIdentifier)) {
                writeTypes.insert(t)
            }
        }
        if !payload.sleepStages.isEmpty {
            writeTypes.insert(HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!)
        }

        try await store.requestAuthorization(toShare: writeTypes, read: [])
    }

    func importPayload(_ payload: ExportPayload) async {
        isRunning = true
        status = "Importing…"
        result = nil

        var res = ImportResult()

        let isoFmt = ISO8601DateFormatter()
        isoFmt.formatOptions = [.withInternetDateTime]

        func parseDate(_ s: String) -> Date? {
            isoFmt.date(from: s)
        }

        // --- Quantities ---
        var quantitySamples: [HKSample] = []
        for q in payload.quantities {
            guard
                let start = parseDate(q.startDate),
                let end = parseDate(q.endDate),
                let qType = HKQuantityType.quantityType(forIdentifier: HKQuantityTypeIdentifier(rawValue: q.typeIdentifier))
            else {
                res.errors.append("Skipped unknown type: \(q.typeIdentifier)")
                res.skipped += 1
                continue
            }

            let hkUnit = hkUnitFor(q.unit)
            guard let unit = hkUnit else {
                res.errors.append("Unknown unit '\(q.unit)' for \(q.typeIdentifier)")
                res.skipped += 1
                continue
            }

            let quantity = HKQuantity(unit: unit, doubleValue: q.value)
            var metadata: [String: Any] = ["HKExternalUUID": q.externalUUID]
            q.sourceMetadata?.forEach { metadata[$0.key] = $0.value }

            let sample = HKQuantitySample(
                type: qType,
                quantity: quantity,
                start: start,
                end: end,
                metadata: metadata
            )
            quantitySamples.append(sample)
        }

        if !quantitySamples.isEmpty {
            do {
                try await store.save(quantitySamples)
                res.written += quantitySamples.count
            } catch {
                res.errors.append("Quantity write failed: \(error.localizedDescription)")
            }
        }

        // --- Sleep stages ---
        let sleepType = HKObjectType.categoryType(forIdentifier: .sleepAnalysis)!
        var sleepSamples: [HKSample] = []
        for s in payload.sleepStages {
            guard
                let start = parseDate(s.startDate),
                let end = parseDate(s.endDate),
                let value = sleepValue(s.stage)
            else {
                res.skipped += 1
                continue
            }

            let sample = HKCategorySample(
                type: sleepType,
                value: value,
                start: start,
                end: end,
                metadata: ["HKExternalUUID": s.externalUUID]
            )
            sleepSamples.append(sample)
        }

        if !sleepSamples.isEmpty {
            do {
                try await store.save(sleepSamples)
                res.written += sleepSamples.count
            } catch {
                res.errors.append("Sleep write failed: \(error.localizedDescription)")
            }
        }

        result = res
        status = "Done: \(res.written) written, \(res.skipped) skipped"
        isRunning = false
    }

    private func sleepValue(_ stage: String) -> Int? {
        switch stage {
        case "inBed":    return HKCategoryValueSleepAnalysis.inBed.rawValue
        case "asleep":   return HKCategoryValueSleepAnalysis.asleepUnspecified.rawValue
        case "awake":    return HKCategoryValueSleepAnalysis.awake.rawValue
        case "light":    return HKCategoryValueSleepAnalysis.asleepCore.rawValue
        case "deep":     return HKCategoryValueSleepAnalysis.asleepDeep.rawValue
        case "rem":      return HKCategoryValueSleepAnalysis.asleepREM.rawValue
        default:         return nil
        }
    }

    private func hkUnitFor(_ unit: String) -> HKUnit? {
        switch unit {
        case "count/min":  return HKUnit.count().unitDivided(by: .minute())
        case "ms":         return HKUnit.secondUnit(with: .milli)
        case "%":          return HKUnit.percent()
        case "kcal":       return HKUnit.kilocalorie()
        case "degC":       return HKUnit.degreeCelsius()
        default:           return try? HKUnit(from: unit)
        }
    }
}
