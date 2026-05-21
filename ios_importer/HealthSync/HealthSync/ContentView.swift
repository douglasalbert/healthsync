import SwiftUI
import UniformTypeIdentifiers

struct ContentView: View {
    @StateObject private var importer = HKImporter()
    @State private var showFilePicker = false
    @State private var loadedPayload: ExportPayload?
    @State private var loadError: String?
    @State private var fileName: String?

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                Spacer()

                Image(systemName: "heart.text.square.fill")
                    .font(.system(size: 64))
                    .foregroundStyle(.red)

                Text("HealthSync Importer")
                    .font(.title2.bold())

                Text("Select a healthsync export file to import WHOOP data into Apple Health.")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)

                if let name = fileName {
                    Label(name, systemImage: "doc.fill")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }

                if let payload = loadedPayload {
                    GroupBox {
                        VStack(alignment: .leading, spacing: 8) {
                            LabeledContent("Period", value: formatPeriod(payload))
                            LabeledContent("Quantity samples", value: "\(payload.quantities.count)")
                            LabeledContent("Sleep stage segments", value: "\(payload.sleepStages.count)")
                        }
                    }
                    .padding(.horizontal)
                }

                if let err = loadError {
                    Text(err)
                        .font(.footnote)
                        .foregroundStyle(.red)
                        .padding(.horizontal)
                }

                if let result = importer.result {
                    GroupBox("Import Result") {
                        VStack(alignment: .leading, spacing: 8) {
                            LabeledContent("Written", value: "\(result.written)")
                            LabeledContent("Skipped", value: "\(result.skipped)")
                            if !result.errors.isEmpty {
                                Text(result.errors.joined(separator: "\n"))
                                    .font(.caption)
                                    .foregroundStyle(.orange)
                            }
                        }
                    }
                    .padding(.horizontal)
                }

                Spacer()

                VStack(spacing: 12) {
                    Button {
                        showFilePicker = true
                    } label: {
                        Label("Choose Export File", systemImage: "folder")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                    .disabled(importer.isRunning)

                    Button {
                        Task { await doImport() }
                    } label: {
                        Label(
                            importer.isRunning ? "Importing…" : "Import to Health",
                            systemImage: "arrow.down.heart.fill"
                        )
                        .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(loadedPayload == nil || importer.isRunning)
                }
                .padding()
            }
            .navigationTitle("HealthSync")
        }
        .fileImporter(
            isPresented: $showFilePicker,
            allowedContentTypes: [.json],
            allowsMultipleSelection: false
        ) { result in
            handleFilePick(result)
        }
    }

    private func handleFilePick(_ result: Result<[URL], Error>) {
        loadedPayload = nil
        loadError = nil
        importer.result = nil

        switch result {
        case .failure(let err):
            loadError = "Could not open file: \(err.localizedDescription)"
        case .success(let urls):
            guard let url = urls.first else { return }
            fileName = url.lastPathComponent
            guard url.startAccessingSecurityScopedResource() else {
                loadError = "Permission denied accessing file"
                return
            }
            defer { url.stopAccessingSecurityScopedResource() }

            do {
                let data = try Data(contentsOf: url)
                loadedPayload = try JSONDecoder().decode(ExportPayload.self, from: data)
            } catch {
                loadError = "Failed to parse file: \(error.localizedDescription)"
            }
        }
    }

    private func doImport() async {
        guard let payload = loadedPayload else { return }
        do {
            try await importer.requestAuthorization(for: payload)
            await importer.importPayload(payload)
        } catch {
            importer.status = "Authorization failed: \(error.localizedDescription)"
        }
    }

    private func formatPeriod(_ p: ExportPayload) -> String {
        let start = String(p.periodStart.prefix(10))
        let end = String(p.periodEnd.prefix(10))
        return "\(start) → \(end)"
    }
}
