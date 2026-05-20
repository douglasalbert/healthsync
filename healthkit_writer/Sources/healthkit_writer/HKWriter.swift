import Foundation
import HealthKit

class HKWriter {
    private let store = HKHealthStore()

    // MARK: - Authorization

    func requestAuthorization(for payload: Payload) throws {
        guard HKHealthStore.isHealthDataAvailable() else {
            throw HKWriterError.unavailable
        }

        var shareTypes = Set<HKSampleType>()

        for sample in payload.quantities {
            if let t = quantityType(for: sample.typeIdentifier) {
                shareTypes.insert(t)
            }
        }
        if !payload.sleepStages.isEmpty,
           let t = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) {
            shareTypes.insert(t)
        }

        let sema = DispatchSemaphore(value: 0)
        var authError: Error?

        store.requestAuthorization(toShare: shareTypes, read: []) { _, error in
            authError = error
            sema.signal()
        }
        sema.wait()

        if let error = authError {
            throw error
        }
    }

    // MARK: - Write

    func write(payload: Payload) -> (written: Int, skipped: Int) {
        var samples: [HKSample] = []

        for q in payload.quantities {
            if let sample = makeQuantitySample(q) {
                samples.append(sample)
            }
        }

        for s in payload.sleepStages {
            if let sample = makeSleepSample(s) {
                samples.append(sample)
            }
        }

        guard !samples.isEmpty else {
            return (0, 0)
        }

        let sema = DispatchSemaphore(value: 0)
        var written = 0
        var skipped = 0

        store.save(samples) { success, _ in
            if success {
                written = samples.count
            } else {
                skipped = samples.count
            }
            sema.signal()
        }
        sema.wait()

        return (written, skipped)
    }

    // MARK: - Sample builders

    private func makeQuantitySample(_ q: QuantitySample) -> HKQuantitySample? {
        guard let type = quantityType(for: q.typeIdentifier),
              let unit = hkUnit(for: q.unit) else {
            return nil
        }

        let quantity = HKQuantity(unit: unit, doubleValue: q.value)
        var metadata: [String: Any] = [
            HKMetadataKeyExternalUUID: q.externalUUID,
            "HKMetadataKeySourceName": "WHOOP",
        ]
        q.sourceMetadata?.forEach { metadata[$0.key] = $0.value }

        return HKQuantitySample(
            type: type,
            quantity: quantity,
            start: q.startDate,
            end: q.endDate,
            metadata: metadata
        )
    }

    private func makeSleepSample(_ s: SleepStageSample) -> HKCategorySample? {
        guard let type = HKObjectType.categoryType(forIdentifier: .sleepAnalysis) else {
            return nil
        }

        let value = sleepValue(for: s.stage)
        let metadata: [String: Any] = [
            HKMetadataKeyExternalUUID: s.externalUUID,
            "HKMetadataKeySourceName": "WHOOP",
        ]

        return HKCategorySample(
            type: type,
            value: value,
            start: s.startDate,
            end: s.endDate,
            metadata: metadata
        )
    }

    // MARK: - Type / unit mapping

    private func quantityType(for identifier: String) -> HKQuantityType? {
        guard let hkId = hkQuantityIdentifier(for: identifier) else { return nil }
        return HKObjectType.quantityType(forIdentifier: hkId)
    }

    private func hkQuantityIdentifier(for id: String) -> HKQuantityTypeIdentifier? {
        switch id {
        case "HKQuantityTypeIdentifierHeartRate":
            return .heartRate
        case "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":
            return .heartRateVariabilitySDNN
        case "HKQuantityTypeIdentifierRestingHeartRate":
            return .restingHeartRate
        case "HKQuantityTypeIdentifierRespiratoryRate":
            return .respiratoryRate
        case "HKQuantityTypeIdentifierOxygenSaturation":
            return .oxygenSaturation
        default:
            return nil
        }
    }

    private func hkUnit(for unit: String) -> HKUnit? {
        switch unit {
        case "count/min":
            return HKUnit.count().unitDivided(by: .minute())
        case "ms":
            return HKUnit.secondUnit(with: .milli)
        case "%":
            return HKUnit.percent()
        default:
            return nil
        }
    }

    private func sleepValue(for stage: String) -> Int {
        switch stage {
        case "awake":
            return HKCategoryValueSleepAnalysis.awake.rawValue
        case "light":
            if #available(macOS 14, *) {
                return HKCategoryValueSleepAnalysis.asleepCore.rawValue
            }
            return HKCategoryValueSleepAnalysis.asleep.rawValue
        case "rem":
            if #available(macOS 14, *) {
                return HKCategoryValueSleepAnalysis.asleepREM.rawValue
            }
            return HKCategoryValueSleepAnalysis.asleep.rawValue
        case "deep":
            if #available(macOS 14, *) {
                return HKCategoryValueSleepAnalysis.asleepDeep.rawValue
            }
            return HKCategoryValueSleepAnalysis.asleep.rawValue
        default:
            return HKCategoryValueSleepAnalysis.awake.rawValue
        }
    }
}

enum HKWriterError: Error {
    case unavailable
}
